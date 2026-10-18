"""Pending sales actions: a quote the AI sales agent prepared, waiting for a person (suggest) or sent by the agent (autopilot).

Every state change is ONE guarded UPDATE (``... WHERE status = 'pending'``), so a double click, two staff members, or a staff
approval racing an autopilot send can never send twice; the loser gets a 409. Sending is always quote_send_service (the same
checks, links and message as the staff "Send quote" button): this module never builds a link or a message itself, and payment
-> booking -> invoice -> confirmation stays with quote_payment_service.

Audited: sales_action.created / approved / rejected / sent / failed (chained audit rows; the agent's own rows have a NULL actor
and ``payload.actor = "ai_sales_agent"``).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.inquiry_360 import InquiryQuote
from app.models.sales_action import LIVE_STATUSES, SalesAction
from app.models.user import User
from app.services import quote_send_service as qss
from app.services import quote_service as qs

log = structlog.get_logger()

AGENT = {"actor": "ai_sales_agent"}
WINDOW = timedelta(hours=24)


class ActionError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def summary_of(primary: InquiryQuote, fallback: Optional[InquiryQuote]) -> dict:
    """What staff need to judge the quote at a glance, copied from the issued snapshots (never recomputed)."""
    def one(r: InquiryQuote) -> dict:
        snap = r.snapshot or {}
        return {"quote_id": r.id, "package_name": snap.get("package_name") or r.package_key,
                "destination": (snap.get("destination") or {}).get("name"), "check_in": r.check_in.isoformat() if r.check_in else None,
                "check_out": r.check_out.isoformat() if r.check_out else None, "guests": r.guests, "total": snap.get("total"),
                "advance": snap.get("advance"), "gst": snap.get("gst"), "valid_until": snap.get("valid_until"),
                "inclusions": snap.get("inclusions") or [], "exclusions": snap.get("exclusions") or [],
                "at_actuals": snap.get("at_actuals") or []}
    out = one(primary)
    out["quote_number"] = qss.quote_number(primary)
    out["fallback"] = one(fallback) if fallback is not None else None
    return out


def recent(db: Session, tenant_id: str, inquiry_id: str, requirement_key: Optional[str] = None) -> Optional[SalesAction]:
    """The live action of the last 24 hours for this lead (and requirement, when given), newest first."""
    q = db.query(SalesAction).filter(SalesAction.tenant_id == tenant_id, SalesAction.inquiry_id == inquiry_id,
                                     SalesAction.status.in_(LIVE_STATUSES), SalesAction.created_at >= _now() - WINDOW)
    if requirement_key:
        q = q.filter(SalesAction.requirement_key == requirement_key)
    return q.order_by(SalesAction.created_at.desc()).first()


def create(db: Session, tenant_id: str, *, inquiry_id: str, conversation_id: Optional[str], primary: InquiryQuote,
           fallback: Optional[InquiryQuote], mode: str, requirement_key: str, hold_reasons: list[str]) -> SalesAction:
    """A new pending action. Earlier pending actions of the lead are superseded (the guest changed what they want). Flushes."""
    for old in db.query(SalesAction).filter(SalesAction.tenant_id == tenant_id, SalesAction.inquiry_id == inquiry_id,
                                            SalesAction.status == "pending").all():
        old.status = "superseded"
    row = SalesAction(tenant_id=tenant_id, inquiry_id=inquiry_id, conversation_id=conversation_id, quote_id=primary.id, mode=mode,
                      status="pending", requirement_key=requirement_key, summary=summary_of(primary, fallback),
                      hold_reasons=list(hold_reasons))
    db.add(row)
    db.flush()
    append_audit(db, tenant_id=tenant_id, action="sales_action.created", target_type="sales_action", target_id=row.id,
                 payload={"inquiry_id": inquiry_id, "quote_id": primary.id, "mode": mode, "hold_reasons": list(hold_reasons), **AGENT})
    return row


def _claim(db: Session, tenant_id: str, action_id: str, user_id: Optional[str], to: str) -> bool:
    n = (db.query(SalesAction).filter(SalesAction.id == action_id, SalesAction.tenant_id == tenant_id, SalesAction.status == "pending")
         .update({SalesAction.status: to, SalesAction.decided_by: user_id, SalesAction.decided_at: _now()}, synchronize_session=False))
    db.flush()
    return n == 1


def _get(db: Session, tenant_id: str, action_id: str) -> SalesAction:
    row = db.query(SalesAction).filter_by(id=action_id, tenant_id=tenant_id).first()
    if row is None:
        raise ActionError("not_found", "Sales action not found.", 404)
    return row


def _visible(db: Session, user: User, row: SalesAction) -> bool:
    from app.services.quote_builder_service import visible_inquiry
    return visible_inquiry(db, user, row.inquiry_id) is not None


# ─── staff ───────────────────────────────────────────────────────────────────────────────────────────────

def approve(db: Session, user: User, action_id: str) -> dict:
    """Send THAT quote group through quote_send_service.send (links + WhatsApp quote). A refusal (quote no longer valid, stay not
    confirmed, Razorpay not connected ...) puts the action back to pending with the reason, so it can be fixed and retried."""
    row = _get(db, user.tenant_id, action_id)
    if not _visible(db, user, row):
        raise ActionError("not_found", "Sales action not found.", 404)
    if not _claim(db, user.tenant_id, action_id, user.id, "sending"):
        raise ActionError("not_pending", f"This action is already {_get(db, user.tenant_id, action_id).status}.", 409)
    append_audit(db, tenant_id=user.tenant_id, actor_user_id=user.id, action="sales_action.approved", target_type="sales_action",
                 target_id=action_id, payload={"quote_id": row.quote_id, "inquiry_id": row.inquiry_id})
    db.commit()
    try:
        result = qss.send(db, user, row.quote_id)
    except qs.QuoteError as exc:                   # quote_send_service commits what it made (links) before it raises
        db.query(SalesAction).filter_by(id=action_id, tenant_id=user.tenant_id).update(
            {SalesAction.status: "pending", SalesAction.last_error: exc.message, SalesAction.decided_by: None,
             SalesAction.decided_at: None}, synchronize_session=False)
        append_audit(db, tenant_id=user.tenant_id, actor_user_id=user.id, action="sales_action.send_refused", target_type="sales_action",
                     target_id=action_id, payload={"code": exc.code, "message": exc.message[:300]})
        db.commit()
        raise ActionError(exc.code, exc.message, exc.status)
    _finish(db, user.tenant_id, action_id, result, user.id)
    return out(db, _get(db, user.tenant_id, action_id))


def reject(db: Session, user: User, action_id: str, reason: Optional[str] = None) -> dict:
    row = _get(db, user.tenant_id, action_id)
    if not _visible(db, user, row):
        raise ActionError("not_found", "Sales action not found.", 404)
    if not _claim(db, user.tenant_id, action_id, user.id, "rejected"):
        raise ActionError("not_pending", f"This action is already {_get(db, user.tenant_id, action_id).status}.", 409)
    append_audit(db, tenant_id=user.tenant_id, actor_user_id=user.id, action="sales_action.rejected", target_type="sales_action",
                 target_id=action_id, payload={"quote_id": row.quote_id, "reason": (reason or "")[:300]})
    db.commit()
    return out(db, _get(db, user.tenant_id, action_id))


def _finish(db: Session, tenant_id: str, action_id: str, result: dict, actor_id: Optional[str]) -> None:
    msg = (result or {}).get("message") or {}
    sent = msg.get("status") in ("queued", "already_sent")
    db.query(SalesAction).filter_by(id=action_id, tenant_id=tenant_id).update(
        {SalesAction.status: "sent" if sent else "failed", SalesAction.result: {"message": msg},
         SalesAction.last_error: None if sent else msg.get("message")}, synchronize_session=False)
    append_audit(db, tenant_id=tenant_id, actor_user_id=actor_id, action="sales_action.sent" if sent else "sales_action.failed",
                 target_type="sales_action", target_id=action_id, payload={"message_status": msg.get("status"), **({} if actor_id else AGENT)})
    db.commit()


# ─── the agent (autopilot) ───────────────────────────────────────────────────────────────────────────────

def start_autopilot(db: Session, tenant_id: str, action_id: str) -> bool:
    """pending -> sending for the agent itself. False when a person already decided. The caller commits and queues the task."""
    return _claim(db, tenant_id, action_id, None, "sending")


def deliver_autopilot(db: Session, tenant_id: str, action_id: str) -> dict:
    """The body of Celery ``sales_agent.send_quote``: the agent's own send. A refusal marks the action failed and gives staff a
    task, so a quote the agent could not send is never silently dropped."""
    row = db.query(SalesAction).filter_by(id=action_id, tenant_id=tenant_id).first()
    if row is None or row.status != "sending":
        return {"status": "ignored"}
    if qss.template_status(db, tenant_id) != "approved":
        return _agent_failed(db, row, "The WhatsApp quote template is not approved, so the agent did not send it.")
    try:
        result = qss.send_as_agent(db, tenant_id, row.quote_id)
    except qs.QuoteError as exc:
        return _agent_failed(db, _get(db, tenant_id, action_id), exc.message)
    _finish(db, tenant_id, action_id, result, None)
    return {"status": _get(db, tenant_id, action_id).status}


def _agent_failed(db: Session, row: SalesAction, reason: str) -> dict:
    from app.services import task_service
    row.status, row.last_error = "failed", reason[:500]
    append_audit(db, tenant_id=row.tenant_id, action="sales_action.failed", target_type="sales_action", target_id=row.id,
                 payload={"reason": reason[:300], **AGENT})
    task_service.create_task(db, row.tenant_id, f"Send the quote yourself: {reason[:120]}", priority="high",
                             inquiry_id=row.inquiry_id, conversation_id=row.conversation_id, due_date=_now(), commit=False)
    db.commit()
    log.warning("sales_agent_send_failed", tenant_id=row.tenant_id, action_id=row.id)
    return {"status": "failed"}


# ─── reading ─────────────────────────────────────────────────────────────────────────────────────────────

def out(db: Session, row: SalesAction, can_decide: bool = False) -> dict:
    primary = db.query(InquiryQuote).filter_by(id=row.quote_id, tenant_id=row.tenant_id).first()
    readiness = None
    if row.status == "pending" and primary is not None:
        from app.models.guest import Guest
        from app.models.inquiry import Inquiry
        inquiry = db.query(Inquiry).filter_by(id=row.inquiry_id, tenant_id=row.tenant_id).first()
        guest = db.query(Guest).filter_by(id=inquiry.guest_id, tenant_id=row.tenant_id).first() if inquiry else None
        readiness = qss.readiness(db, row.tenant_id, primary, qss.group_rows(db, row.tenant_id, primary), guest)
    return {"id": row.id, "inquiry_id": row.inquiry_id, "conversation_id": row.conversation_id, "message_id": row.message_id,
            "quote_id": row.quote_id, "kind": row.kind, "mode": row.mode, "status": row.status, "summary": row.summary or {},
            "hold_reasons": row.hold_reasons or [], "last_error": row.last_error, "decided_by": row.decided_by,
            "decided_at": row.decided_at.isoformat() if row.decided_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None, "readiness": readiness, "can_decide": can_decide}


def list_for(db: Session, user: User, inquiry_id: Optional[str], conversation_id: Optional[str], status: Optional[str],
             can_decide: bool) -> list[dict]:
    from app.services.quote_builder_service import visible_inquiry
    q = db.query(SalesAction).filter(SalesAction.tenant_id == user.tenant_id)
    if inquiry_id:
        q = q.filter(SalesAction.inquiry_id == inquiry_id)
    if conversation_id:
        q = q.filter(SalesAction.conversation_id == conversation_id)
    if status:
        q = q.filter(SalesAction.status == status)
    rows = q.order_by(SalesAction.created_at.desc()).limit(20).all()
    return [out(db, r, can_decide) for r in rows if visible_inquiry(db, user, r.inquiry_id) is not None]
