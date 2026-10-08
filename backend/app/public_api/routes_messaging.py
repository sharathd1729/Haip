"""Public API: WhatsApp and Instagram messaging.

Sending is asynchronous: a 202 means HAIP accepted the message and queued it, not that it was
delivered. Follow the message with GET /messages/{id} (or the message.* webhooks).
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

import structlog

from app.api.v1.endpoints.messaging import TemplateStatus, WATemplate
from app.core.database import get_db
from app.models.api_key import ApiKey
from app.models.conversation import (
    ChannelType, Conversation, Message, MessageDeliveryState, MessageDirection,
)
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.public_api import schemas as sc
from app.public_api.deps import ApiError, require_scope
from app.services import wa_template_service as wts
from app.services.identity_service import resolve_gid
from app.services.wa_subscriber_import import validate_phone

log = structlog.get_logger()
router = APIRouter()

_WINDOW = timedelta(hours=24)
_STATUS = {"pending": "queued", "queued": "queued", "sent": "sent", "delivered": "delivered",
           "read": "read", "failed": "failed", "rejected": "failed"}


# ── shared helpers ───────────────────────────────────────────────────────────

def _state(m: Message) -> str:
    if m.direction == MessageDirection.INBOUND:
        return "received"
    raw = m.delivery_state.value if hasattr(m.delivery_state, "value") else (m.delivery_state or "queued")
    return _STATUS.get(str(raw), "queued")


def _message_out(m: Message, to: Optional[str] = None) -> dict:
    meta = m.channel_metadata or {}
    return {
        "id": m.id,
        "conversation_id": m.conversation_id,
        "channel": m.channel.value if hasattr(m.channel, "value") else m.channel,
        "direction": m.direction.value if hasattr(m.direction, "value") else m.direction,
        "status": _state(m),
        "error": getattr(m, "delivery_error", None) if _state(m) == "failed" else None,
        "to": to,
        "text": m.body,
        "template_name": meta.get("template_name"),
        "local_message_id": meta.get("local_message_id"),
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def _idem(key: ApiKey, local_id: Optional[str], header: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """(stored idempotency key, the caller's own id). Same id from the same API key = same message."""
    own = (local_id or header or "").strip() or None
    if not own:
        return None, None
    return hashlib.sha1(f"{key.id}:{own}".encode()).hexdigest(), own


def _existing(db: Session, tenant_id: str, stored: Optional[str]) -> Optional[Message]:
    if not stored:
        return None
    return db.query(Message).filter(Message.tenant_id == tenant_id, Message.idempotency_key == stored).first()


def _guest_for_phone(db: Session, tenant_id: str, phone: str, name: Optional[str], create: bool) -> tuple[Optional[str], str]:
    normalized, problem = validate_phone(phone)
    if problem:
        raise ApiError(422, "invalid_phone", f"'{phone}' is not a valid phone number. {problem}")
    if create:
        gid, _ = resolve_gid(db=db, tenant_id=tenant_id, signal_type="phone", value=normalized, source="public_api",
                             guest_fields={"name": (name or "").strip() or "Unknown", "phone": normalized})
        return gid, normalized
    guest = db.query(Guest).filter_by(tenant_id=tenant_id, phone=normalized, is_deleted=False).first()
    return (guest.id if guest else None), normalized


def _open_conversation(db: Session, tenant_id: str, guest_id: str, channel: ChannelType, create: bool) -> Optional[Conversation]:
    conv = (db.query(Conversation).filter_by(tenant_id=tenant_id, guest_id=guest_id, channel=channel, is_open=True)
            .order_by(Conversation.last_message_at.desc()).first())
    if conv or not create:
        return conv
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    conv = Conversation(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id, channel=channel, is_open=True,
        ai_mode=(getattr(tenant, "wa_ai_mode_default", None) or "shadow"),
        first_response_at=datetime.now(timezone.utc).isoformat(),   # we wrote first: no reply is owed yet
    )
    db.add(conv)
    db.flush()
    return conv


def _window_open(db: Session, conv: Conversation) -> bool:
    last = (db.query(func.max(Message.created_at))
            .filter(Message.conversation_id == conv.id, Message.direction == MessageDirection.INBOUND).scalar())
    if last is None:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - last <= _WINDOW


# ── templates + sending ──────────────────────────────────────────────────────

@router.get("/whatsapp/templates", tags=["WhatsApp"], summary="List approved templates", response_model=sc.TemplateList)
def list_templates(key: ApiKey = Depends(require_scope("messages:read")), db: Session = Depends(get_db)):
    """Approved WhatsApp templates you can send, with how many values each one needs."""
    rows = db.query(WATemplate).filter_by(tenant_id=key.tenant_id, status=TemplateStatus.APPROVED).order_by(WATemplate.name).all()
    out = []
    for t in rows:
        needed = wts.template_variables(t.components)
        body = next((c.get("text") for c in (t.components or []) if (c.get("type") or "").upper() == "BODY"), None)
        out.append({"name": t.name, "language": t.language, "category": str(getattr(t.category, "value", t.category)),
                    "body": body, "body_variables": len(needed.get("body", [])), "header_variables": len(needed.get("header", []))})
    return {"data": out}


class SendTemplate(BaseModel):
    to: str = Field(description="Recipient phone number with country code, e.g. +919876543210. Numbers without a country code are read as Indian.")
    template_name: str = Field(description="Name of an approved template (see GET /whatsapp/templates).")
    language: Optional[str] = Field(None, description="Template language code, e.g. en or en_US. Needed only if the template exists in several languages.")
    variables: list[str] = Field(default_factory=list, description="Values for {{1}}, {{2}}... in the template body, in order.")
    recipient_name: Optional[str] = Field(None, description="Used only if this phone number is new to HAIP.")
    local_message_id: Optional[str] = Field(None, max_length=100, description="Your own id for this message. Sending the same id again returns the original message instead of sending twice.")


@router.post("/whatsapp/messages/template", tags=["WhatsApp"], summary="Send a template message", status_code=202, response_model=sc.MessageResponse)
def send_template(
    body: SendTemplate,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    key: ApiKey = Depends(require_scope("messages:send")),
    db: Session = Depends(get_db),
):
    """Send an approved template to any phone number, at any time. Templates are the only message type WhatsApp
    allows outside the 24-hour reply window, so use them for alerts and reminders. The message also appears in the
    guest's thread in the HAIP inbox. Returns 202: the message is queued, not yet delivered."""
    tid = key.tenant_id
    stored, own = _idem(key, body.local_message_id, idempotency_key)
    prior = _existing(db, tid, stored)
    if prior:
        return {"data": _message_out(prior, to=body.to), "idempotent_replay": True}

    q = db.query(WATemplate).filter_by(tenant_id=tid, name=body.template_name, status=TemplateStatus.APPROVED)
    if body.language:
        q = q.filter(WATemplate.language == body.language)
    templates = q.order_by(WATemplate.language).all()
    if not templates:
        raise ApiError(404, "template_not_found", f"No approved template named '{body.template_name}'"
                       f"{' in ' + body.language if body.language else ''}. List them with GET /whatsapp/templates.")
    if len(templates) > 1 and not body.language:
        raise ApiError(422, "language_required", f"'{body.template_name}' exists in several languages "
                       f"({', '.join(t.language for t in templates)}). Pass `language`.")
    tmpl = templates[0]

    needed = wts.template_variables(tmpl.components)
    if needed.get("header"):
        raise ApiError(422, "unsupported_template", "This template has a variable in its header, which the API can't fill yet.")
    expected = len(needed.get("body", []))
    if len(body.variables) != expected:
        raise ApiError(422, "variable_mismatch", f"Template '{tmpl.name}' needs {expected} value{'s' if expected != 1 else ''}; {len(body.variables)} given.")

    guest_id, phone = _guest_for_phone(db, tid, body.to, body.recipient_name, create=True)
    conv = _open_conversation(db, tid, guest_id, ChannelType.WHATSAPP, create=True)

    comp = next((c for c in (tmpl.components or []) if (c.get("type") or "").upper() == "BODY"), None)
    text = comp.get("text", "") if comp else tmpl.name
    for i, v in enumerate(body.variables, start=1):
        text = text.replace(f"{{{{{i}}}}}", str(v))

    msg = Message(
        id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.OUTBOUND,
        channel=ChannelType.WHATSAPP, body=text, sender_name=f"API: {key.name}"[:255], was_approved=True,
        delivery_state=MessageDeliveryState.QUEUED, channel_status="queued", idempotency_key=stored,
        channel_metadata={"template_id": tmpl.id, "template_name": tmpl.name, "source": "public_api",
                          "api_key_id": key.id, "local_message_id": own},
    )
    db.add(msg)
    conv.last_message_at = datetime.now(timezone.utc).isoformat()
    db.commit()
    db.refresh(msg)

    from app.workers.tasks.send_whatsapp import send_whatsapp_template
    send_whatsapp_template.delay(message_id=msg.id, tenant_id=tid, template_name=tmpl.name,
                                 language_code=tmpl.language or "en_US", variables=body.variables)
    log.info("public_api_template_queued", message_id=msg.id, api_key_id=key.id, template=tmpl.name)
    return {"data": _message_out(msg, to=phone)}


class SendText(BaseModel):
    to: Optional[str] = Field(None, description="Recipient phone number. Use this or conversation_id.")
    conversation_id: Optional[str] = Field(None, description="Conversation to reply in (from GET /conversations or a webhook).")
    text: str = Field(min_length=1, max_length=4096)
    local_message_id: Optional[str] = Field(None, max_length=100, description="Your own id for this message; resending the same id returns the original.")


def _send_text(db: Session, key: ApiKey, body: SendText, channel: ChannelType, idem_header: Optional[str]) -> dict:
    tid = key.tenant_id
    stored, own = _idem(key, body.local_message_id, idem_header)
    prior = _existing(db, tid, stored)
    if prior:
        return {"data": _message_out(prior, to=body.to), "idempotent_replay": True}
    if not body.to and not body.conversation_id:
        raise ApiError(422, "missing_target", "Provide `to` (phone number) or `conversation_id`.")

    phone = None
    if body.conversation_id:
        conv = db.query(Conversation).filter_by(id=body.conversation_id, tenant_id=tid).first()
        if not conv:
            raise ApiError(404, "conversation_not_found", "No conversation with this id.")
        if conv.channel != channel:
            raise ApiError(422, "wrong_channel", f"This is a {getattr(conv.channel, 'value', conv.channel)} conversation.")
    else:
        if channel != ChannelType.WHATSAPP:
            raise ApiError(422, "missing_target", "Instagram conversations can't be started by phone number. Use `conversation_id`.")
        guest_id, phone = _guest_for_phone(db, tid, body.to, None, create=False)
        conv = _open_conversation(db, tid, guest_id, channel, create=False) if guest_id else None
        if not conv:
            raise ApiError(422, "session_window_closed", "There is no open conversation with this number, so a free-text message "
                           "can't be sent. Send an approved template first (POST /whatsapp/messages/template).")

    if not _window_open(db, conv):
        label = "WhatsApp" if channel == ChannelType.WHATSAPP else "Instagram"
        raise ApiError(422, "session_window_closed", f"{label} only allows free-text messages within 24 hours of the guest's last message."
                       + (" Send an approved template instead (POST /whatsapp/messages/template)." if channel == ChannelType.WHATSAPP else ""))

    msg = Message(
        id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.OUTBOUND, channel=channel,
        body=body.text, sender_name=f"API: {key.name}"[:255], was_approved=True, delivery_state=MessageDeliveryState.QUEUED,
        channel_status="queued", idempotency_key=stored,
        channel_metadata={"source": "public_api", "api_key_id": key.id, "local_message_id": own},
    )
    db.add(msg)
    conv.last_message_at = datetime.now(timezone.utc).isoformat()
    db.commit()
    db.refresh(msg)

    if channel == ChannelType.WHATSAPP:
        from app.workers.tasks.send_whatsapp import send_whatsapp
        send_whatsapp.delay(message_id=msg.id, tenant_id=tid)
    else:
        from app.workers.tasks.send_instagram_dm import send_instagram_dm
        send_instagram_dm.delay(message_id=msg.id, tenant_id=tid)
    log.info("public_api_text_queued", message_id=msg.id, api_key_id=key.id, channel=channel.value)
    return {"data": _message_out(msg, to=phone)}


@router.post("/whatsapp/messages/text", tags=["WhatsApp"], summary="Send a free-text message", status_code=202, response_model=sc.MessageResponse)
def send_whatsapp_text(body: SendText, idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
                       key: ApiKey = Depends(require_scope("messages:send")), db: Session = Depends(get_db)):
    """Reply in an open conversation. WhatsApp only allows this within 24 hours of the guest's last message; after
    that the API answers 422 `session_window_closed` and you should send a template instead."""
    return _send_text(db, key, body, ChannelType.WHATSAPP, idempotency_key)


@router.post("/instagram/messages/text", tags=["Instagram"], summary="Send an Instagram DM", status_code=202, response_model=sc.MessageResponse)
def send_instagram_text(body: SendText, idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
                        key: ApiKey = Depends(require_scope("messages:send")), db: Session = Depends(get_db)):
    """Reply to a guest on Instagram. Instagram only allows replies within 24 hours of the guest's last message, and
    a conversation can only be started by the guest, so `conversation_id` is required."""
    return _send_text(db, key, body, ChannelType.INSTAGRAM, idempotency_key)


# ── reading ──────────────────────────────────────────────────────────────────

@router.get("/messages/{message_id}", tags=["Messages"], summary="Get a message and its delivery status", response_model=sc.MessageResponse)
def get_message(message_id: str, key: ApiKey = Depends(require_scope("messages:read")), db: Session = Depends(get_db)):
    """`status` moves queued, sent, delivered, read, or failed (with `error`)."""
    m = db.query(Message).filter_by(id=message_id, tenant_id=key.tenant_id).first()
    if not m:
        raise ApiError(404, "not_found", "No message with this id.")
    return {"data": _message_out(m)}


@router.get("/conversations", tags=["Messages"], summary="Find conversations by phone number", response_model=sc.ConversationList)
def list_conversations(
    phone: str = Query(description="Guest phone number, with country code"),
    channel: Optional[str] = Query(None, description="whatsapp or instagram"),
    key: ApiKey = Depends(require_scope("messages:read")),
    db: Session = Depends(get_db),
):
    """The conversation ids for a guest, to use with the text endpoints or to read messages."""
    guest_id, _ = _guest_for_phone(db, key.tenant_id, phone, None, create=False)
    if not guest_id:
        return {"data": []}
    q = db.query(Conversation).filter_by(tenant_id=key.tenant_id, guest_id=guest_id)
    if channel:
        try:
            q = q.filter(Conversation.channel == ChannelType(channel))
        except ValueError:
            raise ApiError(422, "invalid_parameter", "channel must be whatsapp or instagram.")
    rows = q.order_by(Conversation.last_message_at.desc()).limit(20).all()
    return {"data": [{"id": c.id, "channel": getattr(c.channel, "value", c.channel), "is_open": bool(c.is_open),
                      "last_message_at": c.last_message_at, "reply_window_open": _window_open(db, c)} for c in rows]}


@router.get("/conversations/{conversation_id}/messages", tags=["Messages"], summary="List messages in a conversation", response_model=sc.MessageList)
def list_messages(
    conversation_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    key: ApiKey = Depends(require_scope("messages:read")),
    db: Session = Depends(get_db),
):
    """Newest first. Internal staff notes are never included. Prefer the message.received webhook over polling this."""
    conv = db.query(Conversation).filter_by(id=conversation_id, tenant_id=key.tenant_id).first()
    if not conv:
        raise ApiError(404, "not_found", "No conversation with this id.")
    q = db.query(Message).filter(Message.conversation_id == conv.id, Message.tenant_id == key.tenant_id,
                                 Message.is_internal.isnot(True))
    total = q.count()
    rows = q.order_by(Message.created_at.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return {"data": [_message_out(m) for m in rows],
            "meta": {"page": page, "per_page": per_page, "total": total, "total_pages": max(1, (total + per_page - 1) // per_page)}}
