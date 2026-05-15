"""WhatsApp Cloud API message processing."""
import uuid
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
from app.models.guest import Guest
from app.models.tenant import Tenant
import structlog

log = structlog.get_logger()


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
    db = SessionLocal()
    try:
        phone_number_id = value.get("metadata", {}).get("phone_number_id", "")

        # Find tenant by WhatsApp phone number ID
        tenant = db.query(Tenant).filter_by(whatsapp_phone_number_id=phone_number_id).first()
        if not tenant:
            log.warning("tenant_not_found_for_wa_number", phone_number_id=phone_number_id)
            return

        for msg in value.get("messages", []):
            _handle_inbound_message(db, tenant, msg, value.get("contacts", []))

        db.commit()
    finally:
        db.close()


def _handle_inbound_message(db, tenant: Tenant, msg: dict, contacts: list):
    from_number = "+" + msg.get("from", "").lstrip("+")
    wa_msg_id = msg.get("id", "")
    msg_type = msg.get("type", "text")

    # Dedup check
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

    db.flush()  # ensure message.id is assigned before we pass it

    log.info("wa_message_stored", guest=from_number, conversation=conversation.id)

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
