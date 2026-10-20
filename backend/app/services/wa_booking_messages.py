"""Send a booking's WhatsApp templates (confirmation, payment received, balance due) to the guest.

``send_guest_template`` is the one way HAIP sends these templates (``send_booking_template`` for a booking, the quote
sender for ratha_quote_payment_v1, "qt:{quote group}:{event}" keys): it finds or opens the guest's WhatsApp
conversation, writes the outbound Message (so it shows in the inbox and on the booking) and queues the normal
``tasks.send_whatsapp_template`` task. Guarantees:
* never twice for the same (booking, event): ``Message.idempotency_key`` = "bk:{stay_id}:{event}" (partial unique index
  from migration 005, plus a read first because SQLite tests have no such index);
* never an unapproved template: it skips, logs and audits ``booking.message_not_sent`` with the reason instead;
* the document (invoice PDF) and the pay-link ending ride on the message (channel_metadata) and are signed at send time.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState, MessageDirection
from app.models.property import Stay
from app.models.tenant import Tenant
from app.services import wa_booking_pack as pack
from app.services import wa_template_service as wts
from app.services.invoice_pdf import inr_text

log = structlog.get_logger()

IDEM_PREFIX = "bk:"


def inr(v) -> str:
    return inr_text(v).replace("Rs. ", "₹")


def day(d: date) -> str:
    return f"{d:%a}, {d.day} {d:%b}"


def idempotency_key(owner_id: str, event: str, prefix: str = IDEM_PREFIX) -> str:
    """"bk:{stay_id}:{event}" for a booking, "qt:{quote group id}:{event}" for a sent quote."""
    part = event if len(event) <= 24 else hashlib.sha256(event.encode()).hexdigest()[:24]
    return f"{prefix}{owner_id}:{part}"


def rzp_suffix(short_url: str) -> Optional[str]:
    """"https://rzp.io/i/AbC" -> "i/AbC". None when the link is not on rzp.io (then the button cannot point at it)."""
    url = (short_url or "").strip()
    if not url.lower().startswith(pack.RZP_BASE) or len(url) <= len(pack.RZP_BASE):
        return None
    tail = url[len(pack.RZP_BASE):]
    return tail if all(c.isalnum() or c in "/_-" for c in tail) else None


class Target:
    """What a template message is about: its idempotency key prefix, the audit rows and Message.channel_metadata.
    Booking: Target("booking", stay.id, "bk:", {...}, "booking"); sent quote: Target("inquiry_quote", group id, "qt:", {...}, "quote")."""
    def __init__(self, kind: str, target_id: str, prefix: str, meta: dict, audit_prefix: str):
        self.kind, self.id, self.prefix, self.meta, self.audit_prefix = kind, target_id, prefix, meta, audit_prefix


def _skip(db: Session, tenant_id: str, target: Target, template: str, event: str, reason: str, actor_id: Optional[str]) -> dict:
    log.warning(f"{target.audit_prefix}_message_not_sent", tenant_id=tenant_id, target_id=target.id, template=template,
                message_event=event, reason=reason)
    append_audit(db, tenant_id=tenant_id, actor_user_id=actor_id, action=f"{target.audit_prefix}.message_not_sent",
                 target_type=target.kind, target_id=target.id, payload={"template": template, "event": event, "reason": reason})
    db.commit()
    return {"status": "skipped", "reason": reason, "message_id": None}


def _open_conversation(db: Session, tenant: Tenant, guest_id: str) -> Conversation:
    """The guest's one open WhatsApp conversation, or a new one (unique index: one open WA thread per guest)."""
    conv = (db.query(Conversation).filter_by(tenant_id=tenant.id, guest_id=guest_id, channel=ChannelType.WHATSAPP, is_open=True)
            .order_by(Conversation.last_message_at.desc()).first())
    if conv:
        return conv
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest_id, channel=ChannelType.WHATSAPP, is_open=True,
                        ai_mode=(getattr(tenant, "wa_ai_mode_default", None) or "shadow"),
                        first_response_at=datetime.now(timezone.utc).isoformat())   # we wrote first: no reply is owed
    db.add(conv)
    db.flush()
    return conv


def _default_kind(actor_user_id: Optional[str]) -> str:
    """A person pressed Send (a quote, a pay link) = their contact; HAIP sending by itself (booking confirmation,
    payment received, balance reminder) = "system", which never counts as a person contacting the guest."""
    return "human" if actor_user_id else "system"


def send_booking_template(db: Session, tenant_id: str, stay: Stay, template_name: str, variables: list[str], *,
                          event: str, document: Optional[dict] = None, url_suffix: Optional[str] = None,
                          actor_user_id: Optional[str] = None, sender_name: str = "HAIP") -> dict:
    """Queue one template for this booking's guest. Returns {"status": "queued"|"duplicate"|"skipped", "reason",
    "message_id"}. ``document`` = {"key": storage key, "filename": "Invoice ....pdf"}. Commits."""
    target = Target("booking", stay.id, IDEM_PREFIX, {"source": "booking", "booking_id": stay.id, "booking_event": event}, "booking")
    return send_guest_template(db, tenant_id, stay.guest, template_name, variables, target=target, event=event, document=document,
                               url_suffix=url_suffix, actor_user_id=actor_user_id, sender_name=sender_name)


def send_guest_template(db: Session, tenant_id: str, guest, template_name: str, variables: list[str], *, target: Target,
                        event: str, document: Optional[dict] = None, url_suffix: Optional[str] = None,
                        actor_user_id: Optional[str] = None, sender_name: str = "HAIP", sender_kind: Optional[str] = None,
                        autonomous: bool = False) -> dict:
    """Queue one approved template to a guest, at most once per (target, event). Same return as send_booking_template.
    ``autonomous`` = HAIP sent it with no person involved (a lead playbook): it never counts as a person's contact."""
    from app.api.v1.endpoints.messaging import TemplateStatus, WATemplate
    from app.workers.tasks.send_whatsapp import _bad_number_reason

    key = idempotency_key(target.id, event, target.prefix)
    prior = db.query(Message.id).filter_by(tenant_id=tenant_id, idempotency_key=key).first()
    if prior:
        return {"status": "duplicate", "reason": "Already sent.", "message_id": prior[0]}

    tmpl = (db.query(WATemplate).filter_by(tenant_id=tenant_id, name=template_name, status=TemplateStatus.APPROVED)
            .order_by(WATemplate.language).first())
    if tmpl is None:
        return _skip(db, tenant_id, target, template_name, event, "template not approved", actor_user_id)

    needed = wts.template_variables(tmpl.components)
    if needed.get("header") or len(needed.get("body", [])) != len(variables):
        return _skip(db, tenant_id, target, template_name, event,
                     f"template needs {len(needed.get('body', []))} values, HAIP gave {len(variables)}", actor_user_id)
    header = next((c for c in tmpl.components or [] if (c.get("type") or "").upper() == "HEADER"), None)
    if header and (header.get("format") or "").upper() == "DOCUMENT" and not (document and document.get("key")):
        return _skip(db, tenant_id, target, template_name, event, "no document to attach", actor_user_id)
    url_index = next((i for c in tmpl.components or [] if (c.get("type") or "").upper() == "BUTTONS"
                      for i, b in enumerate(c.get("buttons") or [])
                      if (b.get("type") or "").upper() == "URL" and wts.variable_indices(b.get("url"))), None)
    if url_index is not None and not url_suffix:
        return _skip(db, tenant_id, target, template_name, event, "no payment link to put on the button", actor_user_id)

    phone = guest.phone if guest else ""
    bad = _bad_number_reason(phone if phone and not str(phone).startswith("DELETED_") else "")
    if bad:   # the checker's text quotes the number; logs and the audit trail must not (PII)
        reason = "the guest has no phone number" if not phone else "the guest's phone number is not a valid WhatsApp number"
        return _skip(db, tenant_id, target, template_name, event, reason, actor_user_id)

    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    conv = _open_conversation(db, tenant, guest.id)
    body = next((c.get("text", "") for c in tmpl.components or [] if (c.get("type") or "").upper() == "BODY"), tmpl.name)
    for i, v in enumerate(variables, start=1):
        body = body.replace("{{%d}}" % i, str(v))
    meta = {"template_id": tmpl.id, "template_name": tmpl.name, **target.meta}
    if document and document.get("key"):
        meta["document"] = {"key": document["key"], "filename": document.get("filename") or "document.pdf"}
    if url_index is not None:
        meta["button_params"] = {str(url_index): url_suffix}
    msg = Message(id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id, direction=MessageDirection.OUTBOUND,
                  channel=ChannelType.WHATSAPP, body=body, sender_id=actor_user_id, sender_name=sender_name[:255],
                  was_approved=True, delivery_state=MessageDeliveryState.QUEUED, channel_status="queued",
                  idempotency_key=key, channel_metadata=meta, sender_kind=sender_kind or _default_kind(actor_user_id),
                  sent_autonomously=autonomous)
    db.add(msg)
    conv.last_message_at = datetime.now(timezone.utc).isoformat()
    append_audit(db, tenant_id=tenant_id, actor_user_id=actor_user_id, action=f"{target.audit_prefix}.message_queued",
                 target_type=target.kind, target_id=target.id, payload={"template": template_name, "event": event, "message_id": msg.id})
    try:
        db.commit()
    except IntegrityError:                          # a concurrent sender took the same (target, event)
        db.rollback()
        return {"status": "duplicate", "reason": "Already sent.", "message_id": None}

    from app.workers.tasks.send_whatsapp import send_whatsapp_template
    try:
        send_whatsapp_template.delay(message_id=msg.id, tenant_id=tenant_id, template_name=tmpl.name,
                                     language_code=tmpl.language or "en", variables=[str(v) for v in variables])
    except Exception as exc:  # noqa: BLE001 -- broker down: say so on the message instead of leaving it "queued" forever
        log.error(f"{target.audit_prefix}_message_enqueue_failed", tenant_id=tenant_id, message_id=msg.id, error=str(exc))
        msg.delivery_state = MessageDeliveryState.FAILED
        msg.channel_status = "failed"
        msg.delivery_error = "Could not queue the message. Use Retry in the inbox."
        db.commit()
        return {"status": "skipped", "reason": "could not queue the message", "message_id": msg.id}
    log.info(f"{target.audit_prefix}_message_queued", tenant_id=tenant_id, message_id=msg.id, template=tmpl.name, message_event=event)
    return {"status": "queued", "reason": None, "message_id": msg.id}


# ── The booking events ───────────────────────────────────────────────────────

def _first(stay: Stay) -> str:
    name = (stay.guest.name if stay.guest else "") or ""
    return name.strip().split(" ")[0] if name.strip() else "there"


def _trip(db: Session, tenant: Tenant, stay: Stay) -> str:
    if stay.inquiry_id:
        from app.models.inquiry import Inquiry
        inq = db.query(Inquiry.route_mentioned).filter_by(id=stay.inquiry_id, tenant_id=tenant.id).first()
        if inq and inq[0]:
            return str(inq[0])[:80]
    return f"{tenant.brand_name or tenant.name} trip"


def _doc(inv) -> Optional[dict]:
    if not inv or not inv.pdf_media_key:
        return None
    label = "Receipt" if inv.kind == "receipt" else "Invoice"
    return {"key": inv.pdf_media_key, "filename": f"{label} {inv.number.replace('/', '-')}.pdf"}


def send_confirmation(db: Session, tenant: Tenant, stay: Stay, invoice, fin: dict) -> dict:
    from app.services.invoice_service import booking_ref
    variables = [_first(stay), booking_ref(stay), _trip(db, tenant, stay), day(stay.check_in), day(stay.check_out),
                 stay.property.name if stay.property else "your caravan", inr(fin["paid"]), inr(fin["outstanding"])]
    return send_booking_template(db, tenant.id, stay, pack.BOOKING_CONFIRMED, variables, event="confirmed", document=_doc(invoice))


def send_payment_received(db: Session, tenant: Tenant, stay: Stay, receipt, payment, fin: dict, next_due: Optional[dict]) -> dict:
    from app.services.invoice_service import booking_ref
    if fin["outstanding"] <= 0:
        status = "Your trip is fully paid."
    elif next_due:
        status = f"Balance {inr(fin['outstanding'])}, next {inr(next_due['amount'])} due by {day(date.fromisoformat(next_due['due_date']))}."
    else:
        status = f"Balance {inr(fin['outstanding'])} is due before travel."
    variables = [_first(stay), inr(payment.amount), booking_ref(stay), status]
    return send_booking_template(db, tenant.id, stay, pack.PAYMENT_RECEIVED, variables, event=f"paid:{payment.id[:12]}",
                                 document=_doc(receipt))


def send_balance_due(db: Session, tenant: Tenant, stay: Stay, link, amount, due: date, *, event: str,
                     actor_user_id: Optional[str] = None, sender_name: str = "HAIP") -> dict:
    suffix = rzp_suffix(link.short_url)
    if not suffix:
        target = Target("booking", stay.id, IDEM_PREFIX, {}, "booking")
        return _skip(db, tenant.id, target, pack.BALANCE_DUE, event, "the payment link is not a rzp.io link", actor_user_id)
    variables = [_first(stay), day(stay.check_in), inr(amount), day(due)]
    return send_booking_template(db, tenant.id, stay, pack.BALANCE_DUE, variables, event=event, url_suffix=suffix,
                                 actor_user_id=actor_user_id, sender_name=sender_name)


def send_link_text(db: Session, tenant: Tenant, stay: Stay, link, amount, *, event: str,
                   actor_user_id: Optional[str] = None, sender_name: str = "HAIP") -> dict:
    """The pay link as a normal WhatsApp message, for a guest whose 24-hour window is open (no template needed). Goes on the
    guest's Cloud API conversation, at most once per (booking, event). Same return as send_booking_template."""
    from app.services.booking_agenda_service import whatsapp_state
    from app.workers.tasks.send_whatsapp import _bad_number_reason, send_whatsapp

    target = Target("booking", stay.id, IDEM_PREFIX, {}, "booking")
    key = idempotency_key(stay.id, event)
    prior = db.query(Message.id).filter_by(tenant_id=tenant.id, idempotency_key=key).first()
    if prior:
        return {"status": "duplicate", "reason": "Already sent.", "message_id": prior[0]}
    phone = stay.guest.phone if stay.guest else ""
    if _bad_number_reason(phone if phone and not str(phone).startswith("DELETED_") else ""):
        return _skip(db, tenant.id, target, "text", event, "the guest's phone number is not a valid WhatsApp number", actor_user_id)
    state = whatsapp_state(db, tenant.id, stay.guest_id)
    conv = db.query(Conversation).filter_by(id=state["conversation_id"], tenant_id=tenant.id).first() if state["conversation_id"] else None
    if not state["window_open"] or conv is None:
        return _skip(db, tenant.id, target, "text", event, "the guest's 24-hour WhatsApp window is closed", actor_user_id)
    body = (f"Hi {_first(stay)}, here is the secure link to pay {inr(amount)} for your trip on {day(stay.check_in)}: "
            f"{link.short_url}")
    msg = Message(id=str(uuid.uuid4()), tenant_id=tenant.id, conversation_id=conv.id, direction=MessageDirection.OUTBOUND,
                  channel=ChannelType.WHATSAPP, body=body, sender_id=actor_user_id, sender_name=sender_name[:255],
                  was_approved=True, delivery_state=MessageDeliveryState.QUEUED, channel_status="queued", idempotency_key=key,
                  channel_metadata={"source": "booking", "booking_id": stay.id, "booking_event": event})
    db.add(msg)
    conv.last_message_at = datetime.now(timezone.utc).isoformat()
    append_audit(db, tenant_id=tenant.id, actor_user_id=actor_user_id, action="booking.message_queued", target_type="booking",
                 target_id=stay.id, payload={"template": None, "event": event, "message_id": msg.id})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"status": "duplicate", "reason": "Already sent.", "message_id": None}
    try:
        send_whatsapp.delay(message_id=msg.id, tenant_id=tenant.id)
    except Exception as exc:  # noqa: BLE001 -- broker down: say so on the message instead of leaving it "queued" forever
        log.error("booking_message_enqueue_failed", tenant_id=tenant.id, message_id=msg.id, error=str(exc))
        msg.delivery_state, msg.channel_status = MessageDeliveryState.FAILED, "failed"
        msg.delivery_error = "Could not queue the message. Use Retry in the inbox."
        db.commit()
        return {"status": "skipped", "reason": "could not queue the message", "message_id": msg.id}
    return {"status": "queued", "reason": None, "message_id": msg.id}


def send_guest_text(db: Session, tenant_id: str, guest, text: str, *, target: Target, event: str,
                    actor_user_id: Optional[str] = None, sender_name: str = "HAIP", sender_kind: Optional[str] = None,
                    autonomous: bool = False) -> dict:
    """A plain WhatsApp message to a guest whose 24-hour window is open (no template needed), on their Cloud API
    conversation, at most once per (target, event). Skips (audited) when the window is closed. Same return as
    send_booking_template. Commits."""
    from app.services.booking_agenda_service import whatsapp_state
    from app.workers.tasks.send_whatsapp import _bad_number_reason, send_whatsapp

    key = idempotency_key(target.id, event, target.prefix)
    prior = db.query(Message.id).filter_by(tenant_id=tenant_id, idempotency_key=key).first()
    if prior:
        return {"status": "duplicate", "reason": "Already sent.", "message_id": prior[0]}
    phone = guest.phone if guest else ""
    if _bad_number_reason(phone if phone and not str(phone).startswith("DELETED_") else ""):
        return _skip(db, tenant_id, target, "text", event, "the guest's phone number is not a valid WhatsApp number", actor_user_id)
    state = whatsapp_state(db, tenant_id, guest.id)
    conv = db.query(Conversation).filter_by(id=state["conversation_id"], tenant_id=tenant_id).first() if state["conversation_id"] else None
    if not state["window_open"] or conv is None:
        return _skip(db, tenant_id, target, "text", event, "the guest's 24-hour WhatsApp window is closed", actor_user_id)
    msg = Message(id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id, direction=MessageDirection.OUTBOUND,
                  channel=ChannelType.WHATSAPP, body=text, sender_id=actor_user_id, sender_name=sender_name[:255],
                  was_approved=True, delivery_state=MessageDeliveryState.QUEUED, channel_status="queued", idempotency_key=key,
                  channel_metadata=dict(target.meta), sender_kind=sender_kind or _default_kind(actor_user_id),
                  sent_autonomously=autonomous)
    db.add(msg)
    conv.last_message_at = datetime.now(timezone.utc).isoformat()
    append_audit(db, tenant_id=tenant_id, actor_user_id=actor_user_id, action=f"{target.audit_prefix}.message_queued",
                 target_type=target.kind, target_id=target.id, payload={"template": None, "event": event, "message_id": msg.id})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"status": "duplicate", "reason": "Already sent.", "message_id": None}
    try:
        send_whatsapp.delay(message_id=msg.id, tenant_id=tenant_id)
    except Exception as exc:  # noqa: BLE001 -- broker down: say so on the message instead of leaving it "queued" forever
        log.error(f"{target.audit_prefix}_message_enqueue_failed", tenant_id=tenant_id, message_id=msg.id, error=str(exc))
        msg.delivery_state, msg.channel_status = MessageDeliveryState.FAILED, "failed"
        msg.delivery_error = "Could not queue the message. Use Retry in the inbox."
        db.commit()
        return {"status": "skipped", "reason": "could not queue the message", "message_id": msg.id}
    return {"status": "queued", "reason": None, "message_id": msg.id}


def messages_for_stay(db: Session, tenant_id: str, stay_id: str, limit: int = 30) -> list[dict]:
    rows = (db.query(Message).filter(Message.tenant_id == tenant_id, Message.idempotency_key.like(f"{IDEM_PREFIX}{stay_id}:%"))
            .order_by(Message.created_at.desc()).limit(limit).all())
    labels = {t["name"]: t["label"] for t in pack.PACK}
    out = []
    for m in rows:
        meta = m.channel_metadata or {}
        state = getattr(m.delivery_state, "value", m.delivery_state)
        out.append({"id": m.id, "template": meta.get("template_name"), "label": labels.get(meta.get("template_name"), meta.get("template_name")),
                    "event": meta.get("booking_event"), "status": state, "error": m.delivery_error,
                    "conversation_id": m.conversation_id, "at": m.created_at.isoformat() if m.created_at else None,
                    "has_document": bool(meta.get("document"))})
    return out
