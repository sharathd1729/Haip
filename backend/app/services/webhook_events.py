"""Turns changes to bookings, payments, messages, chats, lead stages and new leads into webhook events.

Listeners on the models catch the change wherever it is made (a staff edit, a sold lead, the
public API, a Razorpay payment, a Celery worker updating a delivery state), note it on the
session, and just before commit write the delivery rows in the same transaction. After the
commit the deliveries are handed to Celery. Importing this module registers the listeners.
"""
from __future__ import annotations

import structlog
from sqlalchemy import event
from sqlalchemy.orm import Session, object_session

from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState, MessageDirection
from app.models.property import Stay
from app.models.stay_finance import (
    StayAddOn, StayDeposit, StayInstalment, StayPayment, StayServiceRequest,
)

log = structlog.get_logger()

_PENDING = "webhook_pending"      # session.info: list of (tenant_id, kind, id, extra)
_TO_SEND = "webhook_to_send"      # session.info: list of (tenant_id, delivery_id)
_SHEETS = "sheets_to_send"        # session.info: list of (tenant_id, guest_id) for the Google Sheets lead sync

_STATE = {"pending": "queued", "queued": "queued", "sent": "sent", "delivered": "delivered",
          "read": "read", "failed": "failed", "rejected": "failed"}
_CHILDREN = (StayAddOn, StayPayment, StayInstalment, StayServiceRequest, StayDeposit)


# Set session.info[SUPPRESS_KEY] = True for bulk historical imports: they must not tell customers'
# systems about bookings that already happened.
SUPPRESS_KEY = "suppress_webhooks"


def _note(session: Session | None, tenant_id: str | None, kind: str, obj_id: str, extra: str = "") -> None:
    if session is None or not tenant_id or session.info.get(SUPPRESS_KEY):
        return
    session.info.setdefault(_PENDING, []).append((tenant_id, kind, obj_id, extra))


# ── model listeners (cheap: they only append to a list) ──────────────────────

def _stay_inserted(_m, _c, target: Stay):
    _note(object_session(target), target.tenant_id, "booking", target.id, "created")


def _stay_updated(_m, _c, target: Stay):
    session = object_session(target)
    if session is None or not session.is_modified(target, include_collections=False):
        return
    changed, old = attr_change(target, "status")
    cancelled = changed and target.status == "cancelled" and old != "cancelled"
    _note(session, target.tenant_id, "booking", target.id, "cancelled" if cancelled else "updated")


def attr_change(target, attr: str):
    """(was it assigned in this flush, its previous value or None if unknown).

    After a commit SQLAlchemy has forgotten old values, so the previous value is often
    unknown even though the attribute was assigned: callers must not depend on it."""
    from sqlalchemy import inspect
    hist = inspect(target).attrs[attr].history
    if not hist.added and not hist.deleted:
        return False, None
    return True, (hist.deleted[0] if hist.deleted else None)


def _child_changed(_m, _c, target):
    _note(object_session(target), target.tenant_id, "booking", target.stay_id, "updated")


def _payment_inserted(_m, _c, target: StayPayment):
    session = object_session(target)
    _note(session, target.tenant_id, "booking", target.stay_id, "updated")
    if target.kind == "payment":
        _note(session, target.tenant_id, "payment", target.id)


_GUEST_CHANNELS = (ChannelType.WHATSAPP, ChannelType.INSTAGRAM)
_OUT = (MessageDeliveryState.SENT, MessageDeliveryState.DELIVERED, MessageDeliveryState.READ)


def _message_inserted(_m, _c, target: Message):
    if target.channel not in _GUEST_CHANNELS or target.is_internal:
        return
    if target.direction == MessageDirection.INBOUND:
        _note(object_session(target), target.tenant_id, "message_received", target.id)
    # Written already sent (personal-WhatsApp mirror of the agent's own reply, Instagram automations). History imports
    # are old messages, not news.
    elif target.delivery_state == MessageDeliveryState.SENT and target.sender_kind != "bridge_history":
        _note(object_session(target), target.tenant_id, "message_sent", target.id)


def _guest_lead(_m, _c, target):
    """lead.created: a guest's lead_identified_at went from empty to set (they shared a usable phone)."""
    if target.lead_identified_at is None:
        return
    changed, old = attr_change(target, "lead_identified_at")
    if changed and old is None:
        _note(object_session(target), target.tenant_id, "lead", target.id)


def _message_updated(_m, _c, target: Message):
    session = object_session(target)
    if session is None or target.direction != MessageDirection.OUTBOUND or target.is_internal:
        return
    if target.channel not in (ChannelType.WHATSAPP, ChannelType.INSTAGRAM):
        return
    changed, old = attr_change(target, "delivery_state")
    if not changed:
        return
    _note(session, target.tenant_id, "message_status", target.id)
    # message.sent once, when it first leaves HAIP (any sender). delivery_state keeps its old value (active history,
    # see register), so a repeat "sent" status never fires twice.
    if target.delivery_state in _OUT and old not in _OUT:
        _note(session, target.tenant_id, "message_sent", target.id)


def _conversation_updated(_m, _c, target: Conversation):
    """conversation.closed: is_open went from True to False (resolved / closed in the inbox, by a rule or the API)."""
    if target.is_open:
        return
    changed, old = attr_change(target, "is_open")
    if changed and old is not False:
        _note(object_session(target), target.tenant_id, "conversation_closed", target.id)


def note_stage_changed(session: Session, inquiry, from_key: str | None, to_key: str) -> None:
    """lead.stage_changed. Called by BOTH stage paths in inquiry_service (_apply_stage and _apply_stage_by_id)."""
    if from_key != to_key:
        _note(session, inquiry.tenant_id, "lead_stage", inquiry.id, f"{from_key or ''}|{to_key}")


# ── commit-time processing ───────────────────────────────────────────────────

def _booking_payload(session: Session, tenant_id: str, stay_id: str):
    from app.public_api.serializers import serialize_bookings
    from sqlalchemy import func
    stay = session.get(Stay, stay_id)
    if stay is None or stay.tenant_id != tenant_id:
        return None
    number = session.query(func.count(Stay.id)).filter(Stay.tenant_id == tenant_id, Stay.created_at <= stay.created_at).scalar()
    return serialize_bookings(session, tenant_id, [stay], {stay.id: number})[0]


def _message_payload(session: Session, tenant_id: str, message_id: str, received: bool):
    from app.models.conversation import Conversation
    from app.models.guest import Guest
    m = session.get(Message, message_id)
    if m is None or m.tenant_id != tenant_id:
        return None
    conv = session.get(Conversation, m.conversation_id)
    guest = session.get(Guest, conv.guest_id) if conv else None
    base = {"id": m.id, "conversation_id": m.conversation_id,
            "channel": m.channel.value if hasattr(m.channel, "value") else m.channel,
            "guest": {"id": guest.id, "name": guest.name, "phone": guest.phone} if guest else None}
    if received:
        return {**base, "text": m.body, "media_url": m.media_url, "received_at": m.created_at.isoformat() if m.created_at else None}
    raw = m.delivery_state.value if hasattr(m.delivery_state, "value") else (m.delivery_state or "queued")
    meta = m.channel_metadata or {}
    status = _STATE.get(str(raw), "queued")
    return {**base, "status": status, "error": getattr(m, "delivery_error", None) if status == "failed" else None,
            "template_name": meta.get("template_name"), "local_message_id": meta.get("local_message_id")}


def _sent_payload(session: Session, tenant_id: str, message_id: str):
    base = _message_payload(session, tenant_id, message_id, received=True)
    if base is None:
        return None
    m = session.get(Message, message_id)
    base.pop("received_at", None)
    sender = m.sender_kind or ("ai_auto" if m.sent_autonomously else ("ai_approved" if m.is_ai_generated else None))
    return {**base, "sender_kind": sender, "sender_name": m.sender_name,
            "template_name": (m.channel_metadata or {}).get("template_name"),
            "sent_at": m.created_at.isoformat() if m.created_at else None}


def _closed_payload(session: Session, tenant_id: str, conversation_id: str):
    from datetime import datetime, timezone
    from app.models.guest import Guest
    c = session.get(Conversation, conversation_id)
    if c is None or c.tenant_id != tenant_id:
        return None
    guest = session.get(Guest, c.guest_id)
    return {"id": c.id, "channel": c.channel.value if hasattr(c.channel, "value") else c.channel,
            "lead_id": c.inquiry_id, "assigned_to": c.assigned_to,
            "guest": {"id": guest.id, "name": guest.name, "phone": guest.phone} if guest else None,
            "closed_at": datetime.now(timezone.utc).isoformat()}


def _stage_payload(session: Session, tenant_id: str, inquiry_id: str, extra: str):
    from datetime import datetime, timezone
    from app.models.guest import Guest
    from app.models.inquiry import Inquiry
    from app.models.pipeline_stage import PipelineStage
    inq = session.get(Inquiry, inquiry_id)
    if inq is None or inq.tenant_id != tenant_id:
        return None
    from_key, _, to_key = extra.partition("|")
    label = session.query(PipelineStage.label).filter_by(id=inq.stage_id, tenant_id=tenant_id).scalar() if inq.stage_id else None
    guest = session.get(Guest, inq.guest_id)
    return {"id": inq.id, "guest": {"id": guest.id, "name": guest.name} if guest else None,
            "from_stage": from_key or None, "to_stage": to_key, "to_stage_label": label,
            "changed_at": datetime.now(timezone.utc).isoformat()}


def _process(session: Session) -> None:
    from app.models.webhook import WebhookEndpoint
    from app.services import webhook_service as ws

    pending = session.info.pop(_PENDING, None)
    if not pending:
        return
    # one event per (tenant, booking) with the strongest reason; payments and messages stand alone
    bookings: dict[tuple[str, str], str] = {}
    singles: list[tuple[str, str, str, str]] = []
    rank = {"created": 3, "cancelled": 2, "updated": 1}
    for tenant_id, kind, obj_id, extra in pending:
        if kind == "booking":
            key = (tenant_id, obj_id)
            if rank[extra] > rank.get(bookings.get(key, ""), 0):
                bookings[key] = extra
        else:
            singles.append((tenant_id, kind, obj_id, extra))

    subscribed: dict[str, list[WebhookEndpoint]] = {}

    def endpoints(tenant_id: str) -> list:
        if tenant_id not in subscribed:
            subscribed[tenant_id] = session.query(WebhookEndpoint).filter(
                WebhookEndpoint.tenant_id == tenant_id, WebhookEndpoint.is_active.is_(True)).all()
        return subscribed[tenant_id]

    def wanted(tenant_id: str, event_type: str) -> bool:
        return any(event_type in (ep.events or []) for ep in endpoints(tenant_id))

    def emit(tenant_id: str, event_type: str, data: dict | None) -> None:
        if data is None:
            return
        for delivery_id in ws.queue_event(session, tenant_id, event_type, data):
            session.info.setdefault(_TO_SEND, []).append((tenant_id, delivery_id))

    for (tenant_id, stay_id), reason in bookings.items():
        event_type = f"booking.{reason}"
        if wanted(tenant_id, event_type):
            emit(tenant_id, event_type, _booking_payload(session, tenant_id, stay_id))
    sheets_on: dict[str, bool] = {}
    for tenant_id, kind, obj_id, extra in singles:
        if kind == "payment" and wanted(tenant_id, "payment.received"):
            p = session.get(StayPayment, obj_id)
            if p is not None:
                emit(tenant_id, "payment.received", {
                    "id": p.id, "booking_id": p.stay_id, "amount": float(p.amount), "method": p.method,
                    "reference": p.reference, "date": p.paid_on.isoformat(), "via_gateway": bool(p.external_id)})
        elif kind == "message_received" and wanted(tenant_id, "message.received"):
            emit(tenant_id, "message.received", _message_payload(session, tenant_id, obj_id, received=True))
        elif kind == "lead":
            from app.models.guest import Guest
            from app.services import google_sheets_service
            g = session.get(Guest, obj_id)
            if g is None or g.tenant_id != tenant_id:
                continue
            if wanted(tenant_id, "lead.created"):
                emit(tenant_id, "lead.created", {
                    "id": g.id, "name": g.name, "phone": g.phone, "email": getattr(g, "email", None),
                    "identified_at": g.lead_identified_at.isoformat() if g.lead_identified_at else None})
            if tenant_id not in sheets_on:
                sheets_on[tenant_id] = google_sheets_service.is_on(session, tenant_id)
            if sheets_on[tenant_id]:
                session.info.setdefault(_SHEETS, []).append((tenant_id, g.id))
        elif kind == "message_sent" and wanted(tenant_id, "message.sent"):
            emit(tenant_id, "message.sent", _sent_payload(session, tenant_id, obj_id))
        elif kind == "conversation_closed" and wanted(tenant_id, "conversation.closed"):
            emit(tenant_id, "conversation.closed", _closed_payload(session, tenant_id, obj_id))
        elif kind == "lead_stage" and wanted(tenant_id, "lead.stage_changed"):
            emit(tenant_id, "lead.stage_changed", _stage_payload(session, tenant_id, obj_id, extra))
        elif kind == "message_status" and wanted(tenant_id, "message.status"):
            emit(tenant_id, "message.status", _message_payload(session, tenant_id, obj_id, received=False))


def _before_commit(session: Session) -> None:
    # SQLAlchemy runs this hook before the commit's own flush, and the model listeners above only
    # fire during a flush. Flush now (the commit would do it next anyway) so every change is seen.
    # A flush error is a real business error and must propagate, so this is outside the try below.
    if session.new or session.dirty or session.deleted:
        session.flush()
    if not session.info.get(_PENDING):
        return
    try:
        _process(session)
    except Exception as exc:  # noqa: BLE001 -- a webhook problem must never block the business write
        session.info.pop(_PENDING, None)
        log.error("webhook_event_processing_failed", error=str(exc), exc_info=True)


def _after_commit(session: Session) -> None:
    sheets = session.info.pop(_SHEETS, None)
    if sheets:
        try:
            from app.workers.tasks.webhook_delivery import send_sheet_row
            for tenant_id, guest_id in sheets:
                send_sheet_row.delay(tenant_id=tenant_id, guest_id=guest_id)
        except Exception as exc:  # noqa: BLE001 -- shortcut: no outbox for sheet rows, a broker outage drops them (logged)
            log.warning("sheet_row_dispatch_failed", error=str(exc))
    to_send = session.info.pop(_TO_SEND, None)
    if not to_send:
        return
    try:
        from app.workers.tasks.webhook_delivery import deliver_webhook
        for tenant_id, delivery_id in to_send:
            deliver_webhook.delay(delivery_id=delivery_id, tenant_id=tenant_id)
    except Exception as exc:  # noqa: BLE001 -- the minute sweeper picks up anything not queued here
        log.warning("webhook_dispatch_failed", error=str(exc))


def _after_rollback(session: Session, *_a) -> None:
    session.info.pop(_PENDING, None)
    session.info.pop(_TO_SEND, None)
    session.info.pop(_SHEETS, None)


def _keep_old(_target, value, _old, _initiator):
    return value


def register() -> None:
    event.listen(Stay, "after_insert", _stay_inserted)
    event.listen(Stay, "after_update", _stay_updated)
    for model in _CHILDREN:
        event.listen(model, "after_update", _child_changed)
        event.listen(model, "after_delete", _child_changed)
        if model is not StayPayment:
            event.listen(model, "after_insert", _child_changed)
    event.listen(StayPayment, "after_insert", _payment_inserted)
    from app.models.guest import Guest
    event.listen(Guest, "after_insert", _guest_lead)
    event.listen(Guest, "after_update", _guest_lead)
    event.listen(Message, "after_insert", _message_inserted)
    event.listen(Message, "after_update", _message_updated)
    event.listen(Conversation, "after_update", _conversation_updated)
    # Keep the previous value of these two even when the object was expired by a commit, so a transition is told
    # apart from re-setting the same value (message.sent, conversation.closed fire once).
    event.listen(Message.delivery_state, "set", _keep_old, active_history=True)
    event.listen(Conversation.is_open, "set", _keep_old, active_history=True)
    event.listen(Session, "before_commit", _before_commit)
    event.listen(Session, "after_commit", _after_commit)
    event.listen(Session, "after_rollback", _after_rollback)


register()
