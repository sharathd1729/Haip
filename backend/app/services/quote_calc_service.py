"""The rate calculator's actions: price (no writes), save to a lead, send on WhatsApp, copy, and the owner's OK for a lowered price.

  save     re-prices on the server (rate_calculator.compute) and stores the snapshot (quote_service.issue_calculated). The lead's
           quote follow-up task moves to the day the quote expires. A price more than the tenant's limit below the suggested one
           (or a discount above the maximum), made by someone who is not the owner or a manager, is saved as
           "pending_approval": a high-priority task + a push go to the owner, and nothing reaches the guest until it is approved.
  send     a Razorpay link for the advance when asked (one per quote, reused while live), then: the guest wrote in the last 24
           hours -> the EXACT text of the preview as a plain WhatsApp message; otherwise the approved quote template
           (ratha_quote_payment_v1, which carries the link as its button) through quote_send_service.deliver. A send that cannot
           happen leaves the quote saved and says why.
  copy     the same text (with the link when one could be made); recorded on the quote as shared by copy.
  stage    when a quote is sent or copied, a lead that is not engaged yet -- an invalid-category stage (Unqualified, RNR) or the
           landing stage of a new lead with a phone (General Enquiry, is_valid_lead_entry; category "valid" in the seeded
           taxonomy) -- moves FORWARD to the tenant's "active" stage through the normal audited path (update_stage_by_id;
           legacy-enum leads through update_stage) so every stage hook fires. Active, Unsuitable, Sold, Lost: never moved.
  approve  owner or manager; never your own quote unless you are the owner; a guarded UPDATE (pending_approval -> issued); audited.
Every function scopes by the caller's tenant and lead visibility. The caller commits unless the docstring says otherwise.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage
from app.models.inquiry_360 import InquiryQuote
from app.models.pipeline_stage import PipelineStage
from app.models.task import Task
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.quote_calculator import CalcIn, CalcSaveIn
from app.services import payment_link_service as pls
from app.services import quote_calc_catalog as cat
from app.services import quote_calc_leads as leads
from app.services import quote_send_service as qss
from app.services import quote_service as qs
from app.services import rate_calculator as rc
from app.services import wa_booking_messages as wbm

log = structlog.get_logger()
APPROVAL_PREFIX = "Approve quote"


def privileged(user: User) -> bool:
    return user.role in (UserRole.OWNER, UserRole.MANAGER)


def _tenant(db: Session, tenant_id: str) -> Tenant:
    return db.query(Tenant).filter_by(id=tenant_id).first()


def _brand(t: Tenant) -> str:
    return t.brand_name or t.name or "your"


def _guest_of(db: Session, tenant_id: str, inquiry: Optional[Inquiry]) -> Optional[Guest]:
    return db.query(Guest).filter_by(id=inquiry.guest_id, tenant_id=tenant_id).first() if inquiry else None


def text_for(db: Session, tenant: Tenant, snap: dict, guest: Optional[Guest], pay_url: Optional[str]) -> str:
    s = cat.settings(db, tenant)
    return rc.render_message(snap, guest_name=guest.name if guest else None, brand=_brand(tenant), greeting=s["greeting"], pay_url=pay_url)


# ─── price (no writes) ───────────────────────────────────────────────────────────────────────────────────

def price(db: Session, user: User, body: CalcIn) -> dict:
    tenant = _tenant(db, user.tenant_id)
    c = rc.compute(db, tenant, body)
    avail = rc.availability(db, user.tenant_id, c) if c.check_in else []
    if not c.ok:
        return rc.result_out(c, None, None, avail, privileged(user))
    snap = rc.to_snapshot(c, body)
    guest = None
    if body.inquiry_id:
        inq = leads._visible(db.query(Inquiry).filter(Inquiry.id == body.inquiry_id, Inquiry.tenant_id == user.tenant_id), user).first()
        guest = _guest_of(db, user.tenant_id, inq)
    text = text_for(db, tenant, snap, guest, rc.PAY_PLACEHOLDER if body.payment_link else None)
    return rc.result_out(c, snap, text, avail, privileged(user))


# ─── helpers ─────────────────────────────────────────────────────────────────────────────────────────────

def _check_target(db: Session, user: User, body: CalcSaveIn) -> None:
    if body.guest_id:
        found = db.query(Guest.id).filter_by(id=body.guest_id, tenant_id=user.tenant_id, is_deleted=False).first()
    else:
        found = leads._visible(db.query(Inquiry.id).filter(Inquiry.id == body.inquiry_id, Inquiry.tenant_id == user.tenant_id),
                               user).first()
    if found is None:
        raise qs.QuoteError("not_found", "Lead not found.", 404)


def _target_inquiry(db: Session, user: User, body: CalcSaveIn) -> tuple[Inquiry, bool]:
    if body.guest_id:
        try:
            return leads.new_trip_lead(db, user, body.guest_id)
        except leads.LeadError as exc:
            raise qs.QuoteError(exc.code, exc.message, exc.status)
    inq = leads._visible(db.query(Inquiry).filter(Inquiry.id == body.inquiry_id, Inquiry.tenant_id == user.tenant_id), user).first()
    if inq is None:
        raise qs.QuoteError("not_found", "Lead not found.", 404)
    if not leads.is_open(inq, leads._stages(db, user.tenant_id)):
        return leads.new_trip_lead(db, user, inq.guest_id)          # a Sold/Lost lead: this trip gets its own lead
    return inq, False


def _stage_view(db: Session, inquiry: Inquiry) -> str:
    st = db.query(PipelineStage).filter_by(id=inquiry.stage_id, tenant_id=inquiry.tenant_id).first() if inquiry.stage_id else None
    return st.label if st else (inquiry.stage.value.replace("_", " ").title() if inquiry.stage else "New")


def _not_engaged(st: PipelineStage) -> bool:
    """A stage a quote moves the lead out of: the "not engaged yet" ones -- any invalid-category stage (Unqualified, RNR) and
    the landing stage a new lead with a phone number gets (General Enquiry, is_valid_lead_entry). Never a closed one, never a
    marketing (collaboration) one, never a stage an agent chose after talking to the guest (Active, Unsuitable, ...)."""
    if st.is_closed_won or st.is_closed_lost or st.category == "marketing" or st.is_collab_entry:
        return False
    return st.category == "invalid" or bool(st.is_valid_lead_entry) or bool(st.is_default_entry)


def _engaged_stage(db: Session, tenant_id: str) -> Optional[PipelineStage]:
    """Where a quoted lead goes: the tenant's "active" stage; without one, its valid-lead entry stage."""
    stages = db.query(PipelineStage).filter_by(tenant_id=tenant_id).all()
    return (next((s for s in stages if s.key == "active" and not (s.is_closed_won or s.is_closed_lost)), None)
            or next((s for s in stages if s.is_valid_lead_entry), None))


def promote_stage(db: Session, user: User, inquiry: Inquiry, how: str) -> dict:
    """Invalid-category stage -> the valid-lead entry stage, through the audited transition paths. Never moves anything else."""
    from app.services import inquiry_service as isvc
    before = _stage_view(db, inquiry)
    reason = f"Quote {how} to the guest"
    try:
        if inquiry.stage_id:
            cur = db.query(PipelineStage).filter_by(id=inquiry.stage_id, tenant_id=inquiry.tenant_id).first()
            if cur is None or not _not_engaged(cur):
                return {"from": before, "to": before, "moved": False}
            target = _engaged_stage(db, inquiry.tenant_id)
            if target is None or target.id == cur.id or target.order <= cur.order:
                return {"from": before, "to": before, "moved": False}
            isvc.update_stage_by_id(db, tenant_id=inquiry.tenant_id, inquiry_id=inquiry.id, new_stage_id=target.id,
                                    actor_user_id=user.id, actor_role=user.role.value, reason=reason)
        elif inquiry.stage == InquiryStage.NEW:
            isvc.update_stage(db, tenant_id=inquiry.tenant_id, inquiry_id=inquiry.id, new_stage=InquiryStage.RESPONDING,
                              actor_user_id=user.id, actor_role=user.role.value, reason=reason)
        else:
            return {"from": before, "to": before, "moved": False}
    except (isvc.InvalidStageTransition, ValueError) as exc:
        log.warning("quote_stage_promotion_skipped", inquiry_id=inquiry.id, error=str(exc)[:200])
        return {"from": before, "to": before, "moved": False}
    db.flush()
    return {"from": before, "to": _stage_view(db, inquiry), "moved": True}


def _close_approval_tasks(db: Session, tenant_id: str, number: str) -> None:
    for t in db.query(Task).filter(Task.tenant_id == tenant_id, Task.is_done.is_(False),
                                   Task.title.like(f"{APPROVAL_PREFIX} {number}%")).all():
        t.is_done, t.completed_at = True, datetime.now(timezone.utc)


def _request_approval(db: Session, user: User, row: InquiryQuote, inquiry: Inquiry, guest: Optional[Guest]) -> None:
    from app.services import task_service
    number = qss.quote_number(row)
    if db.query(Task.id).filter(Task.tenant_id == user.tenant_id, Task.is_done.is_(False),
                                Task.title.like(f"{APPROVAL_PREFIX} {number}%")).first():
        return
    snap = row.snapshot or {}
    why = "; ".join((snap.get("approval") or {}).get("reasons") or []) or "a lowered price"
    owner = db.query(User).filter(User.tenant_id == user.tenant_id, User.role == UserRole.OWNER, User.is_active.is_(True)).first()
    title = f"{APPROVAL_PREFIX} {number} for {(guest.name if guest else None) or 'a guest'}: {wbm.inr(snap.get('total'))}, {why}"
    task_service.create_task(db, user.tenant_id, title[:255], created_by=user.id, due_date=datetime.now(timezone.utc), priority="high",
                             guest_id=inquiry.guest_id, inquiry_id=inquiry.id, assigned_to=owner.id if owner else None, commit=False)
    append_audit(db, tenant_id=user.tenant_id, actor_user_id=user.id, action="quote.approval_requested", target_type="inquiry_quote",
                 target_id=row.id, payload={"inquiry_id": inquiry.id, "total": str(row.amount), "reasons": (snap.get("approval") or {}).get("reasons"),
                                            "suggested_total": snap.get("suggested_total"),
                                            "override_reason": (snap.get("override") or {}).get("reason")})
    _push(user.tenant_id, "A quote needs your OK", f"{user.name or 'An agent'} lowered a quote to {wbm.inr(snap.get('total'))}: {why}.",
          f"/dashboard/quotes?quote={row.id}")


def _push(tenant_id: str, title: str, body: str, url: str) -> None:
    from app.workers.tasks import invoice_tasks
    try:
        invoice_tasks.notify_staff.delay(tenant_id=tenant_id, title=title, body=body, url=url)
    except Exception as exc:  # noqa: BLE001 -- the task row is the record; a push is best-effort
        log.error("quote_approval_push_failed", tenant_id=tenant_id, error=str(exc))


def _ensure_link(db: Session, tenant_id: str, row: InquiryQuote, guest: Optional[Guest], actor_id: Optional[str]):
    """The quote's live Razorpay link, or a new one. Raises pls.PaymentLinkError."""
    link = qss.latest_links(db, tenant_id, [row.id]).get(row.id)
    if qss.is_live(link):
        return link
    snap = row.snapshot or {}
    return pls.create_quote_link(db, tenant_id, row, guest, snap.get("advance"),
                                 description=f"Advance for quote {qss.quote_number(row)}: {snap.get('package_name') or 'trip'}"[:250],
                                 expires_at=row.valid_until, created_by=actor_id)


def _mark_shared(row: InquiryQuote, how: str) -> None:
    row.shared_via = "sent" if how == "sent" or row.shared_via == "sent" else "copied"
    row.shared_at = datetime.now(timezone.utc)


def _usable(row: InquiryQuote) -> Optional[str]:
    """Why this saved quote cannot be shared now, or None."""
    if (row.snapshot or {}).get("kind") != "calculator":
        return "This quote was made in the old quote builder; price it again in the calculator."
    if row.status == "pending_approval":
        return "This quote is waiting for the owner's OK."
    if row.status != "issued" or not row.is_active:
        return f"This quote is {row.status or 'no longer active'}; price it again."
    if row.valid_until is not None and qs._aware(row.valid_until) < datetime.now(timezone.utc):
        return "This quote has expired; price it again."
    return None


# ─── share: send / copy ──────────────────────────────────────────────────────────────────────────────────

def _send(db: Session, user: User, tenant: Tenant, row: InquiryQuote, inquiry: Inquiry, guest: Optional[Guest]) -> dict:
    """{"status": queued|already_sent|not_sent, "code", "message", "channel", "link"}. Never raises; commits on success."""
    snap = row.snapshot or {}
    out = lambda status, code=None, message="", **kw: {"status": status, "code": code, "message": message, **kw}  # noqa: E731
    if not qss.usable_phone(guest):
        return out("not_sent", "no_phone", "The guest has no valid WhatsApp number. Add one on the lead, or copy the quote.")
    window = qss._window_open(db, tenant.id, guest.id)
    wants_link = bool(snap.get("payment_link"))
    if not window:
        if not wants_link:
            return out("not_sent", "needs_template_link", "The guest has not written in the last 24 hours, so WhatsApp allows only the "
                       "approved quote template, which carries the payment link. Turn on the Razorpay link, or copy the quote.")
        if qss.template_status(db, tenant.id) != "approved":
            return out("not_sent", "template_not_approved", "The guest has not written in the last 24 hours and the quote template "
                       "is not approved yet. Copy the quote and send it yourself.")
    link = None
    if wants_link:
        try:
            link = _ensure_link(db, tenant.id, row, guest, user.id)
        except pls.PaymentLinkError as exc:
            return out("not_sent", "razorpay_error" if exc.status == 502 else "razorpay_not_connected", str(exc))
    gid = qss.group_id(row)
    if window:
        text = text_for(db, tenant, snap, guest, link.short_url if link else None)
        event = f"text:{link.external_id if link else 'nolink'}"
        key = wbm.idempotency_key(gid, event, qss.PREFIX)
        if _already(db, tenant.id, key):
            return out("already_sent", None, "This quote was already sent on WhatsApp.", channel="text", link=link)
        append_audit(db, tenant_id=tenant.id, actor_user_id=user.id, action="quote.sent", target_type="inquiry_quote", target_id=gid,
                     payload={"inquiry_id": row.inquiry_id, "event": event, "channel": "text", "links": [link.external_id] if link else []})
        _mark_shared(row, "sent")
        stage = promote_stage(db, user, inquiry, "sent")
        db.commit()
        res = qss._send_text(db, tenant, guest, text, key, {"source": "quote", "quote_id": row.id, "quote_event": event})
        status = "queued" if res["status"] == "queued" else "already_sent"
        return out(status, None, "Sending the quote on WhatsApp." if status == "queued" else "This quote was already sent.",
                   channel="text", link=link, stage=stage)
    event = f"sent:{link.external_id}"
    key = wbm.idempotency_key(gid, event, qss.PREFIX)
    if _already(db, tenant.id, key):
        return out("already_sent", None, "This quote was already sent on WhatsApp.", channel="template", link=link)
    append_audit(db, tenant_id=tenant.id, actor_user_id=user.id, action="quote.sent", target_type="inquiry_quote", target_id=gid,
                 payload={"inquiry_id": row.inquiry_id, "event": event, "channel": "template", "links": [link.external_id]})
    _mark_shared(row, "sent")
    stage = promote_stage(db, user, inquiry, "sent")
    db.commit()
    from app.workers.tasks import quote_tasks
    try:
        quote_tasks.send_with_links.delay(tenant_id=tenant.id, quote_id=row.id, link_id=link.id)
    except Exception as exc:  # noqa: BLE001 -- broker down: the quote and link are saved; say the message did not go
        log.error("quote_calc_enqueue_failed", tenant_id=tenant.id, quote_id=row.id, error=str(exc))
        return out("not_sent", "queue_failed", "Could not queue the WhatsApp message. Copy the quote, or try again.", channel="template",
                   link=link, stage=stage)
    return out("queued", None, "Sending the quote template on WhatsApp.", channel="template", link=link, stage=stage)


def _already(db: Session, tenant_id: str, key: str) -> bool:
    from app.models.conversation import Message
    return db.query(Message.id).filter_by(tenant_id=tenant_id, idempotency_key=key).first() is not None


def _copy(db: Session, user: User, tenant: Tenant, row: InquiryQuote, inquiry: Inquiry, guest: Optional[Guest]) -> dict:
    snap = row.snapshot or {}
    link, warning = None, None
    if snap.get("payment_link"):
        try:
            link = _ensure_link(db, tenant.id, row, guest, user.id)
        except pls.PaymentLinkError as exc:
            warning = f"Copied without a payment link: {exc}"
    text = text_for(db, tenant, snap, guest, link.short_url if link else None)
    append_audit(db, tenant_id=tenant.id, actor_user_id=user.id, action="quote.copied", target_type="inquiry_quote", target_id=row.id,
                 payload={"inquiry_id": row.inquiry_id, "link": link.external_id if link else None})
    _mark_shared(row, "copied")
    stage = promote_stage(db, user, inquiry, "copied")
    return {"status": "copied", "code": None, "message": warning or "", "text": text, "link": link, "stage": stage}


# ─── public actions ──────────────────────────────────────────────────────────────────────────────────────

def _receipt(db: Session, user: User, tenant: Tenant, row: InquiryQuote, inquiry: Inquiry, guest: Optional[Guest], *, how: str,
             lead_created: bool, stage: Optional[dict], result: Optional[dict], follow_up) -> dict:
    snap = row.snapshot or {}
    link = (result or {}).get("link")
    stage = stage or {"from": _stage_view(db, inquiry), "to": _stage_view(db, inquiry), "moved": False}
    return {
        "quote_id": row.id, "quote_number": qss.quote_number(row), "status": row.status, "how": how,
        "lead": {"inquiry_id": inquiry.id, "guest_id": inquiry.guest_id, "guest_name": guest.name if guest else None},
        "lead_created": lead_created, "stage": stage, "follow_up_at": follow_up.isoformat() if follow_up else None,
        "total": snap.get("total"), "advance": snap.get("advance"), "valid_until": snap.get("valid_until"),
        "shared_via": row.shared_via, "approval": snap.get("approval") if row.status == "pending_approval" else None,
        "message": {k: v for k, v in (result or {}).items() if k in ("status", "code", "message", "channel")} or None,
        "message_text": (result or {}).get("text") or text_for(db, tenant, snap, guest, link.short_url if link else None),
        "payment_link": link.short_url if link else None,
    }


def _share(db: Session, user: User, tenant: Tenant, row: InquiryQuote, inquiry: Inquiry, guest: Optional[Guest], action: str) -> dict:
    return _send(db, user, tenant, row, inquiry, guest) if action == "send" else _copy(db, user, tenant, row, inquiry, guest)


def _how(action: str, result: Optional[dict]) -> str:
    if action == "copy":
        return "copied"
    if action == "send":
        return "sent" if result and result["status"] in ("queued", "already_sent") else "saved"
    return "saved"


def save(db: Session, user: User, body: CalcSaveIn) -> dict:
    """Price, store, then send / copy (or only save). Raises qs.QuoteError before any write. Commits."""
    from app.services.quote_builder_service import FOLLOW_UP_PREFIX, _set_next_step
    _check_target(db, user, body)                                     # 404 before anything else (read-only)
    tenant = _tenant(db, user.tenant_id)
    c = rc.compute(db, tenant, body)
    if not c.ok:
        raise qs.QuoteError("not_quotable", c.message, 422)
    inquiry, created = _target_inquiry(db, user, body)
    snap = rc.to_snapshot(c, body)
    pending = c.t["needs_approval"] and not privileged(user)
    row = qs.issue_calculated(db, user.tenant_id, inquiry.id, snap, rc.params_hash(snap), user.id, pending_approval=pending)
    task = _set_next_step(db, user, inquiry, row.valid_until, f"{FOLLOW_UP_PREFIX}: {c.title}")
    guest = _guest_of(db, user.tenant_id, inquiry)
    if row.status == "pending_approval":
        _request_approval(db, user, row, inquiry, guest)
        db.commit()
        return _receipt(db, user, tenant, row, inquiry, guest, how="pending_approval", lead_created=created, stage=None, result=None,
                        follow_up=task.due_date)
    result = _share(db, user, tenant, row, inquiry, guest, body.action) if body.action in ("send", "copy") else None
    db.commit()
    return _receipt(db, user, tenant, row, inquiry, guest, how=_how(body.action, result), lead_created=created,
                    stage=(result or {}).get("stage"), result=result, follow_up=task.due_date)


def _visible_quote(db: Session, user: User, quote_id: str) -> tuple[InquiryQuote, Inquiry]:
    row = db.query(InquiryQuote).filter_by(id=quote_id, tenant_id=user.tenant_id).first()
    inq = (leads._visible(db.query(Inquiry).filter(Inquiry.id == row.inquiry_id, Inquiry.tenant_id == user.tenant_id), user).first()
           if row is not None else None)
    if row is None or inq is None:
        raise qs.QuoteError("not_found", "Quote not found.", 404)
    return row, inq


def share(db: Session, user: User, quote_id: str, action: str) -> dict:
    """Send or copy a saved quote (e.g. once it was approved). Commits."""
    row, inquiry = _visible_quote(db, user, quote_id)
    why = _usable(row)
    if why:
        raise qs.QuoteError("quote_not_shareable", why, 409)
    tenant = _tenant(db, user.tenant_id)
    guest = _guest_of(db, user.tenant_id, inquiry)
    result = _share(db, user, tenant, row, inquiry, guest, action)
    db.commit()
    follow = db.query(Task.due_date).filter(Task.tenant_id == user.tenant_id, Task.inquiry_id == inquiry.id, Task.is_done.is_(False),
                                            Task.title.like("Follow up on the quote%")).order_by(Task.created_at.desc()).first()
    return _receipt(db, user, tenant, row, inquiry, guest, how=_how(action, result), lead_created=False, stage=result.get("stage"),
                    result=result, follow_up=follow[0] if follow else None)


def approve(db: Session, user: User, quote_id: str) -> dict:
    """Owner/manager OK for a lowered price. No self-approval except the owner. Guarded UPDATE; audited. Commits."""
    if not privileged(user):
        raise qs.QuoteError("forbidden", "Only the owner or a manager can approve a quote.", 403)
    row, inquiry = _visible_quote(db, user, quote_id)
    if row.created_by == user.id and user.role != UserRole.OWNER:
        raise qs.QuoteError("self_approval", "You made this quote, so someone else must approve it.", 403)
    now = datetime.now(timezone.utc)
    n = db.execute(update(InquiryQuote).where(InquiryQuote.id == row.id, InquiryQuote.tenant_id == user.tenant_id,
                                              InquiryQuote.status == "pending_approval", InquiryQuote.is_active.is_(True))
                   .values(status="issued", approved_by=user.id, approved_at=now).execution_options(synchronize_session=False)).rowcount
    if n != 1:
        raise qs.QuoteError("not_pending", "This quote is not waiting for approval (it was approved, replaced or withdrawn).", 409)
    db.refresh(row)
    _close_approval_tasks(db, user.tenant_id, qss.quote_number(row))
    snap = row.snapshot or {}
    append_audit(db, tenant_id=user.tenant_id, actor_user_id=user.id, action="quote.approved", target_type="inquiry_quote",
                 target_id=row.id, payload={"inquiry_id": inquiry.id, "total": str(row.amount), "created_by": row.created_by,
                                            "reasons": (snap.get("approval") or {}).get("reasons")})
    db.commit()
    if row.created_by and row.created_by != user.id:
        _push(user.tenant_id, "Quote approved", f"Quote {qss.quote_number(row)} for {wbm.inr(snap.get('total'))} can be sent now.",
              f"/dashboard/quotes?quote={row.id}")
    return view(db, user, row.id)


def view(db: Session, user: User, quote_id: str) -> dict:
    """A saved calculator quote, for /dashboard/quotes?quote=<id> (the approval link)."""
    from app.services.quote_journey import link_out
    row, inquiry = _visible_quote(db, user, quote_id)
    tenant = _tenant(db, user.tenant_id)
    guest = _guest_of(db, user.tenant_id, inquiry)
    snap = row.snapshot or {}
    link = qss.latest_links(db, user.tenant_id, [row.id]).get(row.id)
    live = link if qss.is_live(link) else None
    stages = leads._stages(db, user.tenant_id)
    can_approve = (row.status == "pending_approval" and privileged(user)
                   and (row.created_by != user.id or user.role == UserRole.OWNER))
    names = {u.id: u.name for u in db.query(User).filter(User.tenant_id == user.tenant_id,
                                                         User.id.in_([x for x in (row.created_by, row.approved_by) if x])).all()}
    return {
        "quote_id": row.id, "quote_number": qss.quote_number(row), "status": row.status, "kind": snap.get("kind"),
        "snapshot": snap, "lead": leads.lead_out(inquiry, guest, stages) if guest else None,
        "message_text": text_for(db, tenant, snap, guest, live.short_url if live else (rc.PAY_PLACEHOLDER if snap.get("payment_link") else None)),
        "shared_via": row.shared_via, "shared_at": row.shared_at.isoformat() if row.shared_at else None,
        "created_by_name": names.get(row.created_by), "approved_by_name": names.get(row.approved_by),
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "can_approve": can_approve, "can_share": _usable(row) is None, "blocked_reason": _usable(row),
        "payment_link": link_out(link),
    }
