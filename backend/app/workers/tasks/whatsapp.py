"""WhatsApp Cloud API message processing."""
import hashlib
import uuid
from datetime import datetime, timezone
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


def resolve_wa_tenant(db, phone_number_id: str) -> Tenant | None:
    """
    Resolve which tenant a WhatsApp webhook payload belongs to, by
    phone_number_id. Shared by _process_value (message ingest) and
    webhooks_whatsapp.py's signature verification (T1.1) -- both need the
    same resolution, and duplicating it risked the two drifting apart.
    """
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

    return tenant


def _process_value(value: dict):
    """Process a single WhatsApp webhook value object."""
    from app.core.database import set_tenant_context
    db = SessionLocal()
    try:
        phone_number_id = value.get("metadata", {}).get("phone_number_id", "")
        tenant = resolve_wa_tenant(db, phone_number_id)

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


def _get_wa_access_token(db, tenant_id: str) -> str:
    """whatsapp_meta first, falling back to legacy whatsapp kind.

    Reads from the encrypted credentials_kms_blob, NOT integration.config --
    connect_whatsapp_manual() (integrations.py) never wrote access_token into
    config (only phone_number_id/waba_id/display_phone/verified_name; config
    is spread wholesale into the GET /integrations response, so a secret
    can never go there). access_token only ever existed in the encrypted
    blob. This function's old docstring claimed config.access_token was the
    convention -- it wasn't; every one of the 5 callers of that convention
    (this function, send_whatsapp.py's two tasks, automation_engine.py,
    run_campaign.py) has been silently failing with "missing credentials"
    since whichever tenant first connected via this UI. Fixed here and
    propagated to the other 4 call sites in the same pass."""
    from app.models.integration import Integration
    from app.core.encryption import decrypt_credentials
    integration = db.query(Integration).filter_by(tenant_id=tenant_id, kind="whatsapp_meta").first()
    if not integration:
        integration = db.query(Integration).filter_by(tenant_id=tenant_id, kind="whatsapp").first()
    if not integration or not integration.credentials_kms_blob:
        return ""
    try:
        return decrypt_credentials(integration.credentials_kms_blob).get("access_token", "")
    except Exception:
        return ""


def _fetch_and_store_media(tenant_id: str, message_id: str, access_token: str, media_id: str, msg_type: str) -> tuple[str | None, str | None]:
    """
    T1.2: WhatsApp Cloud API webhooks only ever include a media_id, never a
    direct URL -- resolve it via Meta's Graph API, fetch the bytes with the
    tenant's access token (the resolved download URL is itself short-lived
    and requires the same bearer token), then persist to object storage
    since Meta's URL will have expired well before an agent views the
    message. Returns (s3_key, media_type) or (None, None) on any failure --
    never let a media fetch failure block storing the rest of the message.
    """
    if not access_token or not media_id:
        return None, None
    try:
        import asyncio
        from app.adapters.whatsapp.meta_cloud import MetaCloudAdapter
        from app.services.media_storage import upload_media

        adapter = MetaCloudAdapter(phone_number_id="", access_token=access_token)

        def _run_async(coro):
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

        content, mime_type = _run_async(adapter.fetch_media(media_id))
        s3_key = upload_media(tenant_id, message_id, content, mime_type)
        return s3_key, msg_type
    except Exception as exc:
        log.warning("wa_media_fetch_failed", tenant_id=tenant_id, media_id=media_id, error=str(exc))
        return None, None


def _handle_inbound_message(db, tenant: Tenant, msg: dict, contacts: list):
    from_number = "+" + msg.get("from", "").lstrip("+")
    wa_msg_id = msg.get("id", "")
    msg_type = msg.get("type", "text")

    # Fast-path dedup check (application level)
    existing = db.query(Message).filter_by(channel_message_id=wa_msg_id).first()
    if existing:
        return

    # T1.3: identity resolution goes through the canonical facade --
    # identity_service is the only place for GID resolution, never direct
    # Guest.filter_by() in an endpoint/worker (CLAUDE.md non-negotiable).
    from app.services.identity_service import resolve_gid
    contact = next((c for c in contacts if c.get("wa_id") == msg.get("from")), {})
    contact_name = contact.get("profile", {}).get("name", "")
    guest_id, created = resolve_gid(
        db=db,
        tenant_id=tenant.id,
        signal_type="phone",
        value=from_number,
        source="whatsapp",
        guest_fields={"name": contact_name or "Unknown", "phone": from_number},
    )
    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant.id).first()

    # Find or create open conversation
    conversation = (
        db.query(Conversation)
        .filter_by(tenant_id=tenant.id, guest_id=guest_id, channel=ChannelType.WHATSAPP, is_open=True)
        .first()
    )
    is_new_conversation = conversation is None
    if not conversation:
        conversation = Conversation(
            id=str(uuid.uuid4()),
            tenant_id=tenant.id,
            guest_id=guest_id,
            channel=ChannelType.WHATSAPP,
            is_open=True,
            ai_mode="shadow",
        )
        db.add(conversation)
        db.flush()

    # Extract message body
    body = ""
    media_id = None
    media_type = None

    if msg_type == "text":
        body = msg.get("text", {}).get("body", "")
    elif msg_type in ("image", "video", "audio", "document"):
        media_type = msg_type
        media_id = msg.get(msg_type, {}).get("id", "")
        body = msg.get(msg_type, {}).get("caption", "")
    elif msg_type == "interactive":
        body = str(msg.get("interactive", {}).get("button_reply", {}).get("title", ""))

    # Inbox sort key -- Instagram's inbound handlers
    # (process_instagram_dm.py/process_instagram_comment.py) already set this
    # on every message; this path never did, so any WhatsApp conversation the
    # team hasn't replied to yet has a NULL last_message_at, sorts dead last
    # (nullslast()), and gets pushed off the default 50-item inbox fetch by
    # Instagram's much higher volume -- effectively invisible until someone
    # happens to reply to it first.
    conversation.last_message_at = datetime.now(timezone.utc).isoformat()

    message = Message(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        conversation_id=conversation.id,
        direction=MessageDirection.INBOUND,
        channel=ChannelType.WHATSAPP,
        body=body,
        media_url=None,   # populated below, after the message row (and its id) exists
        media_type=None,
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

    # T1.2: fetch + persist media now that message.id exists (used as the
    # storage key). Best-effort -- a media fetch failure must not roll back
    # the message itself, the text/caption still has value on its own.
    if media_id:
        access_token = _get_wa_access_token(db, tenant.id)
        s3_key, resolved_type = _fetch_and_store_media(tenant.id, message.id, access_token, media_id, media_type)
        if s3_key:
            message.media_url = s3_key
            message.media_type = resolved_type
            db.flush()

    log.info("wa_message_stored", guest_token=_phone_token(from_number), conversation=conversation.id)

    # Leads360 chat auto-create: only fires on the guest's first message in
    # this channel -- a repeat message on an already-open conversation must
    # never spawn a second inquiry (identity_service already dedupes the
    # guest; this dedupes the inquiry).
    if is_new_conversation and body:
        try:
            from app.services.inquiry_service import get_or_create_from_chat
            from app.models.inquiry import InquirySource
            lead_inquiry = get_or_create_from_chat(
                db, tenant.id, guest_id, source=InquirySource.WA_DIRECT.value, message_text=body,
            )
            conversation.inquiry_id = lead_inquiry.id
            db.flush()
        except Exception as exc:
            log.warning("wa_lead_auto_create_failed", tenant_id=tenant.id, error=str(exc))

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
