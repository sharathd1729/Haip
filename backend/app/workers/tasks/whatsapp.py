"""WhatsApp Cloud API message processing."""
import hashlib
import uuid
from sqlalchemy.exc import IntegrityError
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.conversation import (
    Conversation, Message, ChannelType, MessageDirection, MessageDeliveryState,
)
from app.models.guest import Guest
from app.models.tenant import Tenant
import structlog

log = structlog.get_logger()


def _phone_token(phone: str) -> str:
    """One-way hash for log correlation without exposing PII phone numbers."""
    return hashlib.sha256(phone.encode()).hexdigest()[:12]

# Map Meta status strings → our delivery states
_META_STATUS_MAP = {
    "sent":      MessageDeliveryState.SENT,
    "delivered": MessageDeliveryState.DELIVERED,
    "read":      MessageDeliveryState.READ,
    "failed":    MessageDeliveryState.FAILED,
}


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10, name="whatsapp.process_message")
def process_whatsapp_message(self, payload: dict):
    """
    Process inbound WhatsApp message from Meta Cloud API.
    Payload is the full webhook body (may contain multiple entries).
    """
    try:
        entry_list = payload.get("entry", [])
        for entry in entry_list:
            for change in entry.get("changes", []):
                value = change.get("value", {})
                _process_value(value)
    except Exception as exc:
        log.error("whatsapp_processing_failed", error=str(exc))
        raise self.retry(exc=exc)


def _process_value(value: dict):
    """Process a single WhatsApp webhook value object."""
    from app.core.database import set_tenant_context
    db = SessionLocal()
    try:
        phone_number_id = value.get("metadata", {}).get("phone_number_id", "")

        # Primary: find tenant by phone_number_id stored on Tenant row
        tenant = db.query(Tenant).filter_by(whatsapp_phone_number_id=phone_number_id).first()

        # Fallback: look up via active WhatsApp Integration credentials
        # (the connect flow may have stored phone_number_id only in Integration)
        if not tenant and phone_number_id:
            from app.models.integration import Integration
            from app.core.encryption import decrypt_credentials
            integrations = db.query(Integration).filter(
                Integration.kind.in_(["whatsapp", "whatsapp_meta"]),
                Integration.status == "active",
            ).all()
            for intg in integrations:
                try:
                    creds = decrypt_credentials(intg.credentials_kms_blob)
                    if creds.get("phone_number_id") == phone_number_id:
                        tenant = db.query(Tenant).filter_by(id=intg.tenant_id).first()
                        # Back-fill tenant row so future lookups are fast
                        if tenant:
                            tenant.whatsapp_phone_number_id = phone_number_id
                            db.flush()
                        break
                except Exception:
                    continue

        if not tenant:
            log.warning("tenant_not_found_for_wa_number", phone_number_id=phone_number_id)
            return

        # Set RLS context so all subsequent queries are scoped to this tenant
        set_tenant_context(db, str(tenant.id))

        messages = value.get("messages", [])
        for msg in messages:
            _handle_inbound_message(db, tenant, msg, value.get("contacts", []))

        # Handle delivery status callbacks (sent/delivered/read/failed)
        for status_obj in value.get("statuses", []):
            _handle_status_update(db, tenant, status_obj)

        db.commit()
    finally:
        db.close()


def _handle_inbound_message(db, tenant: Tenant, msg: dict, contacts: list):
    from_number = "+" + msg.get("from", "").lstrip("+")
    wa_msg_id = msg.get("id", "")
    msg_type = msg.get("type", "text")

    # Fast-path dedup check (application level)
    existing = db.query(Message).filter_by(channel_message_id=wa_msg_id).first()
    if existing:
        return

    # Dedup / upsert guest
    guest = db.query(Guest).filter_by(tenant_id=tenant.id, phone=from_number).first()
    if not guest:
        contact = next((c for c in contacts if c.get("wa_id") == msg.get("from")), {})
        name = contact.get("profile", {}).get("name", "Unknown")
        guest = Guest(
            id=str(uuid.uuid4()),
            tenant_id=tenant.id,
            phone=from_number,
            name=name,
        )
        db.add(guest)
        db.flush()

    # Find or create open conversation
    conversation = (
        db.query(Conversation)
        .filter_by(tenant_id=tenant.id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
        .first()
    )
    if not conversation:
        conversation = Conversation(
            id=str(uuid.uuid4()),
            tenant_id=tenant.id,
            guest_id=guest.id,
            channel=ChannelType.WHATSAPP,
            is_open=True,
            ai_mode="shadow",
        )
        db.add(conversation)
        db.flush()

    # Extract message body
    body = ""
    media_url = None
    media_type = None

    if msg_type == "text":
        body = msg.get("text", {}).get("body", "")
    elif msg_type in ("image", "video", "audio", "document"):
        media_type = msg_type
        media_url = msg.get(msg_type, {}).get("link", "")
        body = msg.get(msg_type, {}).get("caption", "")
    elif msg_type == "interactive":
        body = str(msg.get("interactive", {}).get("button_reply", {}).get("title", ""))

    message = Message(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        conversation_id=conversation.id,
        direction=MessageDirection.INBOUND,
        channel=ChannelType.WHATSAPP,
        body=body,
        media_url=media_url,
        media_type=media_type,
        channel_message_id=wa_msg_id,
        channel_status="received",
    )
    db.add(message)
    try:
        db.flush()  # ensure message.id is assigned; unique constraint enforces no-duplicate
    except IntegrityError:
        # DB-level unique constraint on channel_message_id caught a race condition.
        db.rollback()
        log.info("wa_message_duplicate_skipped", wa_msg_id=wa_msg_id)
        return

    log.info("wa_message_stored", guest_token=_phone_token(from_number), conversation=conversation.id)

    # Notify SSE subscribers so the inbox updates without a page refresh
    try:
        import redis as _redis
        from app.core.config import settings as _settings
        _r = _redis.Redis.from_url(_settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        import json as _json
        _r.publish(f"sse:{tenant.id}", _json.dumps({
            "event": "message_received",
            "conversation_id": conversation.id,
            "channel": "whatsapp",
            "guest_name": guest.name,
            "guest_phone": guest.phone,
            "preview": body[:120],
        }))
        _r.close()
    except Exception as _sse_exc:
        log.warning("sse_publish_failed", error=str(_sse_exc))

    # Push notification (for staff with PWA on mobile / browser closed)
    try:
        from app.services.push_service import send_to_tenant
        guest_name = guest.name or "Guest"
        send_to_tenant(
            db=db,
            tenant_id=tenant.id,
            title="New WhatsApp message",
            body=f"{guest_name}: {(body or '')[:80]}",
            url=f"/dashboard/inbox?id={conversation.id}",
            tag="haip-message",
            user_id=conversation.assigned_to or None,
        )
    except Exception as _push_exc:
        log.warning("push_notify_failed", error=str(_push_exc))

    # ── D1: Opt-out / opt-in detection ───────────────────────────────────────
    if body and body.strip():
        try:
            from app.services.opt_out_detector import detect_opt_out
            from app.services.opt_out_responder import process_opt_out_event
            result = detect_opt_out(body)
            if result.matched and result.direction:
                process_opt_out_event(
                    db=db,
                    tenant_id=tenant.id,
                    guest_id=guest.id,
                    guest_phone=from_number,
                    direction=result.direction,
                    matched_keyword=result.matched_keyword or "",
                )
                log.info("opt_out_detected", direction=result.direction, kw=result.matched_keyword)
                # For opt-out, skip concierge draft (don't reply twice)
                if result.direction == "opt_out":
                    return
        except Exception as exc:
            log.error("opt_out_detection_failed", error=str(exc))

    # ── Trigger AI Concierge ───────────────────────────────────────────────
    # Only trigger for text/interactive messages (not raw media without caption)
    if body and body.strip():
        try:
            from app.workers.tasks.concierge_draft import concierge_draft
            concierge_draft.apply_async(
                kwargs={
                    "message_id": message.id,
                    "conversation_id": conversation.id,
                    "tenant_id": tenant.id,
                    "channel": "whatsapp",
                },
                countdown=2,  # 2s delay so the DB commit completes first
            )
            log.info(
                "concierge_draft_queued",
                message_id=message.id,
                conversation=conversation.id,
            )
        except Exception as exc:
            log.error("failed_to_queue_concierge_draft", error=str(exc))


def _handle_status_update(db, tenant: Tenant, status_obj: dict):
    """
    Process a Meta delivery-status callback and advance the message's
    delivery_state (sent → delivered → read, or → failed).

    status_obj shape (from Meta docs):
      {
        "id": "<wamid>",
        "status": "delivered" | "read" | "sent" | "failed",
        "timestamp": "...",
        "recipient_id": "...",
        "errors": [{"code": ..., "title": "..."}]   # only on failed
      }
    """
    wamid = status_obj.get("id")
    meta_status = status_obj.get("status", "")

    if not wamid or meta_status not in _META_STATUS_MAP:
        return  # ignore unknown statuses

    new_state = _META_STATUS_MAP[meta_status]

    message = db.query(Message).filter_by(
        tenant_id=tenant.id,
        channel_message_id=wamid,
    ).first()

    if not message:
        log.warning(
            "wa_status_update_no_message",
            wamid=wamid,
            status=meta_status,
        )
        return

    # Only advance state — never go backwards (read > delivered > sent)
    _STATE_RANK = {
        MessageDeliveryState.PENDING:   0,
        MessageDeliveryState.QUEUED:    1,
        MessageDeliveryState.SENT:      2,
        MessageDeliveryState.DELIVERED: 3,
        MessageDeliveryState.READ:      4,
        MessageDeliveryState.FAILED:    5,
        MessageDeliveryState.REJECTED:  5,
    }
    current_rank = _STATE_RANK.get(message.delivery_state, 0)
    new_rank = _STATE_RANK.get(new_state, 0)

    if new_rank >= current_rank:
        message.delivery_state = new_state
        message.channel_status = meta_status

        if meta_status == "failed":
            errors = status_obj.get("errors", [])
            error_msg = "; ".join(
                f"{e.get('code')}: {e.get('title', '')}" for e in errors
            ) if errors else "Meta reported failure"
            message.delivery_error = error_msg[:500]
        else:
            message.delivery_error = None

        log.info(
            "wa_delivery_state_updated",
            message_id=message.id,
            wamid=wamid,
            new_state=new_state.value,
        )
