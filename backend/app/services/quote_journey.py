"""Where a sent quote stands, for GET /quotes/{id} and the quote list: link created -> sent on WhatsApp -> paid ->
booking created -> invoice -> confirmation. Read-only; a handful of queries per quote group.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.audit_event import AuditEvent
from app.models.conversation import Message
from app.models.inquiry_360 import InquiryQuote
from app.models.invoice import Invoice
from app.models.stay_finance import StayPaymentLink
from app.services import quote_send_service as qss
from app.services import wa_booking_messages as wbm


def link_out(link: Optional[StayPaymentLink]) -> Optional[dict]:
    if link is None:
        return None
    status = link.status
    if status == "created" and not qss.is_live(link):
        status = "expired"
    return {"id": link.id, "external_id": link.external_id, "short_url": link.short_url, "amount": float(link.amount),
            "status": status, "expires_at": link.expires_at.isoformat() if link.expires_at else None, "booking_id": link.stay_id,
            "created_at": link.created_at.isoformat() if link.created_at else None,
            "paid_at": link.updated_at.isoformat() if status == "paid" and link.updated_at else None}


def _state(m: Message) -> str:
    return str(getattr(m.delivery_state, "value", m.delivery_state) or "queued")


def _keys(db: Session, tenant_id: str, gid: str, rows: list[InquiryQuote]) -> list[str]:
    """Every idempotency key a send of this group can have used: "sent:{link}" for option 1, "fb:{link}" for option 2."""
    ranks = {r.id: (r.option_rank or 1) for r in rows}
    links = db.query(StayPaymentLink.inquiry_quote_id, StayPaymentLink.external_id).filter(
        StayPaymentLink.tenant_id == tenant_id, StayPaymentLink.inquiry_quote_id.in_(list(ranks))).all()
    return [wbm.idempotency_key(gid, f"{'fb' if ranks.get(qid) == 2 else 'sent'}:{ext}", qss.PREFIX) for qid, ext in links]


def _message(db: Session, tenant_id: str, gid: str, rows_: list[InquiryQuote]) -> tuple[Optional[dict], Optional[dict]]:
    """(the quote template message, the fallback follow-up) -- newest of each."""
    keys = _keys(db, tenant_id, gid, rows_)
    rows = (db.query(Message).filter(Message.tenant_id == tenant_id, Message.idempotency_key.in_(keys))
            .order_by(Message.created_at.desc()).all()) if keys else []
    tmpl = next((m for m in rows if not str((m.channel_metadata or {}).get("quote_event", "")).startswith("fb:")), None)
    fb = next((m for m in rows if str((m.channel_metadata or {}).get("quote_event", "")).startswith("fb:")), None)
    out = lambda m: {"status": _state(m), "error": m.delivery_error, "at": m.created_at.isoformat() if m.created_at else None,  # noqa: E731
                     "message_id": m.id, "conversation_id": m.conversation_id}
    first = out(tmpl) if tmpl else None
    if first is None:     # not written yet (task queued) or skipped: the newest audit row says which
        ev = (db.query(AuditEvent).filter(AuditEvent.tenant_id == tenant_id, AuditEvent.target_type == "inquiry_quote",
                                          AuditEvent.target_id == gid, AuditEvent.action.in_(("quote.sent", "quote.message_not_sent")))
              .order_by(AuditEvent.created_at.desc()).first())
        if ev is not None:
            sent = ev.action == "quote.sent"
            first = {"status": "sending" if sent else "not_sent", "error": None if sent else (ev.payload or {}).get("reason"),
                     "at": ev.created_at.isoformat() if ev.created_at else None, "message_id": None, "conversation_id": None}
    return first, (out(fb) if fb else None)


def journey(db: Session, tenant_id: str, rows: list[InquiryQuote]) -> dict:
    primary = rows[0]
    gid = qss.group_id(primary)
    links = qss.latest_links(db, tenant_id, [r.id for r in rows])
    paid = [(r, links[r.id]) for r in rows if r.id in links and links[r.id].status == "paid"]
    message, fallback_message = _message(db, tenant_id, gid, rows)
    booking_id = next((lk.stay_id for _, lk in paid if lk.stay_id), None)
    invoice = confirmation = None
    if booking_id:
        inv = (db.query(Invoice).filter_by(tenant_id=tenant_id, stay_id=booking_id, kind="invoice")
               .order_by(Invoice.created_at.desc()).first())
        invoice = {"number": inv.number, "id": inv.id} if inv else None
        m = db.query(Message).filter_by(tenant_id=tenant_id, idempotency_key=wbm.idempotency_key(booking_id, "confirmed")).first()
        confirmation = {"status": _state(m), "error": m.delivery_error} if m else None
    needs_staff = None
    if paid and not booking_id:
        needs_staff = "Paid, but no booking was made automatically. See the high-priority task on the lead."
    elif len(paid) > 1:
        needs_staff = "Both options were paid. See the task on the lead (refund or adjust)."
    return {
        "quote_number": qss.quote_number(primary), "group_id": gid,
        "options": [{"quote_id": r.id, "option_rank": r.option_rank or 1, "status": r.status, "amount": str(r.amount),
                     "advance": (r.snapshot or {}).get("advance"), "link": link_out(links.get(r.id))} for r in rows],
        "message": message, "fallback_message": fallback_message,
        "paid": {"quote_id": paid[0][0].id, "option_rank": paid[0][0].option_rank or 1, "amount": float(paid[0][1].amount),
                 "at": link_out(paid[0][1])["paid_at"]} if paid else None,
        "booking_id": booking_id, "invoice": invoice, "confirmation": confirmation, "needs_staff": needs_staff,
        "polling": any(qss.is_live(links.get(r.id)) for r in rows) and not paid,
    }


def decorate(db: Session, tenant_id: str, outs: list[dict]) -> list[dict]:
    """Add each listed option's newest payment link (one query for the lot)."""
    links = qss.latest_links(db, tenant_id, [o["id"] for o in outs])
    for o in outs:
        o["payment_link"] = link_out(links.get(o["id"]))
    return outs
