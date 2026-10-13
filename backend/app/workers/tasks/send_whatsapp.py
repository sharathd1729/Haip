"""
Send WhatsApp message task — uses MetaCloudAdapter.

Delivery state transitions managed here:
  QUEUED → SENT      on Meta API 200
  QUEUED → FAILED    on retry exhaustion or permanent error
"""
import asyncio
from datetime import datetime, timezone
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
from app.models.conversation import Conversation, Message, MessageDeliveryState
from app.models.integration import Integration
from app.adapters.whatsapp.meta_cloud import get_wa_adapter
import structlog

log = structlog.get_logger()


@celery_app.task(bind=True, max_retries=5, default_retry_delay=30, name="tasks.send_whatsapp")
def send_whatsapp(self, message_id: str, tenant_id: str):
    from app.core.database import set_tenant_context
    db = SessionLocal()
    message = None
    try:
        set_tenant_context(db, tenant_id)
        message = db.query(Message).filter_by(id=message_id, tenant_id=tenant_id).first()
        if not message:
            log.error("send_whatsapp_message_not_found", message_id=message_id)
            return

        # Already sent? A redelivered or retried task must not send the same message to the guest a second time (the Meta API
        # has no idempotency key, so the only protection is not calling it again).
        if _already_sent(message):
            log.info("send_whatsapp_already_sent", message_id=message_id)
            return

        conversation = db.query(Conversation).filter_by(id=message.conversation_id).first()
        if not conversation:
            log.error("send_whatsapp_conv_not_found", conversation_id=message.conversation_id)
            return

        # phone_number_id (not secret) comes from integration.config;
        # access_token (secret) comes from the encrypted credentials_kms_blob
        # via _get_wa_access_token -- config never held the token (see that
        # function's docstring), so this used to always fail here with
        # "missing credentials" for every tenant.
        from app.workers.tasks.whatsapp import _get_wa_access_token
        integration = db.query(Integration).filter_by(tenant_id=tenant_id, kind="whatsapp_meta").first()
        if not integration:
            integration = db.query(Integration).filter_by(tenant_id=tenant_id, kind="whatsapp").first()
        if not integration:
            log.error("send_whatsapp_no_integration", tenant_id=tenant_id)
            _mark_failed(db, message, "No WhatsApp integration configured for tenant")
            return

        phone_number_id = (integration.config or {}).get("phone_number_id")
        access_token = _get_wa_access_token(db, tenant_id)

        if not phone_number_id or not access_token:
            log.error("send_whatsapp_missing_credentials", tenant_id=tenant_id)
            _mark_failed(db, message, "Missing phone_number_id or access_token in integration config")
            return

        # Get recipient phone from guest
        from app.models.guest import Guest
        guest = db.query(Guest).filter_by(id=conversation.guest_id).first()
        if not guest:
            _mark_failed(db, message, "Guest not found for conversation")
            return

        bad = _bad_number_reason(guest.phone)
        if bad:
            _mark_failed(db, message, bad)
            return

        adapter = get_wa_adapter(phone_number_id, access_token)

        def _run_async(coro):
            """Run an async coroutine from a sync Celery task safely (Python 3.10+)."""
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

        media_type = getattr(message, "media_type", None)
        media_url  = getattr(message, "media_url", None)
        body_text  = message.body or ""

        if media_type and media_url:
            if media_type == "image":
                result = _run_async(adapter.send_image(to=guest.phone, url=media_url, caption=body_text))
            elif media_type == "video":
                result = _run_async(adapter.send_video(to=guest.phone, url=media_url, caption=body_text))
            elif media_type == "audio":
                result = _run_async(adapter.send_audio(to=guest.phone, url=media_url))
            elif media_type == "document":
                result = _run_async(adapter.send_document(to=guest.phone, url=media_url, caption=body_text))
            else:
                # Unknown media type — fall back to text
                result = _run_async(adapter.send_text(to=guest.phone, body=body_text))
        else:
            result = _run_async(adapter.send_text(to=guest.phone, body=body_text))

        # ── Success: transition to SENT ───────────────────────────────────────
        wamid = result.get("messages", [{}])[0].get("id")
        message.channel_message_id = wamid
        message.channel_status = "sent"
        message.delivery_state = MessageDeliveryState.SENT
        message.delivery_error = None
        message.was_approved = True
        db.commit()

        log.info(
            "whatsapp_sent",
            message_id=message_id,
            wamid=wamid,
            to=_phone_token(guest.phone),       # never the number itself
        )

    except Exception as exc:
        _fail_or_retry(self, db, message, exc, "send_whatsapp_failed", message_id)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, name="tasks.send_whatsapp_template")
def send_whatsapp_template(self, message_id: str, tenant_id: str, template_name: str, language_code: str, variables: list):
    """
    T3.2: send an approved template message (as opposed to send_whatsapp's
    free-form text) -- required when the 24h service window is closed,
    since Meta rejects free-form business-initiated messages outside it.
    Separate task from send_whatsapp because the Meta API call itself is
    different (POST .../messages with type=template, not type=text).
    """
    from app.core.database import set_tenant_context
    db = SessionLocal()
    message = None
    try:
        set_tenant_context(db, tenant_id)
        message = db.query(Message).filter_by(id=message_id, tenant_id=tenant_id).first()
        if not message:
            log.error("send_whatsapp_template_message_not_found", message_id=message_id)
            return

        if _already_sent(message):
            log.info("send_whatsapp_already_sent", message_id=message_id)
            return

        conversation = db.query(Conversation).filter_by(id=message.conversation_id).first()
        if not conversation:
            log.error("send_whatsapp_template_conv_not_found", conversation_id=message.conversation_id)
            return

        integration = db.query(Integration).filter_by(tenant_id=tenant_id, kind="whatsapp_meta").first()
        if not integration:
            integration = db.query(Integration).filter_by(tenant_id=tenant_id, kind="whatsapp").first()
        if not integration:
            _mark_failed(db, message, "No WhatsApp integration configured for tenant")
            return

        from app.workers.tasks.whatsapp import _get_wa_access_token
        phone_number_id = (integration.config or {}).get("phone_number_id")
        access_token = _get_wa_access_token(db, tenant_id)
        if not phone_number_id or not access_token:
            _mark_failed(db, message, "Missing phone_number_id or access_token in integration config")
            return

        from app.models.guest import Guest
        guest = db.query(Guest).filter_by(id=conversation.guest_id).first()
        if not guest or not guest.phone:
            _mark_failed(db, message, "Guest not found or has no phone for conversation")
            return

        bad = _bad_number_reason(guest.phone)
        if bad:
            _mark_failed(db, message, bad)
            return

        adapter = get_wa_adapter(phone_number_id, access_token)
        components = _template_components(db, tenant_id, message, variables)

        def _run_async(coro):
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()

        result = _run_async(adapter.send_template(
            to=guest.phone, template_name=template_name, language_code=language_code, components=components,
        ))

        wamid = result.get("messages", [{}])[0].get("id")
        message.channel_message_id = wamid
        message.channel_status = "sent"
        message.delivery_state = MessageDeliveryState.SENT
        message.delivery_error = None
        message.was_approved = True
        db.commit()

        log.info("whatsapp_template_sent", message_id=message_id, wamid=wamid, template=template_name)

    except Exception as exc:
        _fail_or_retry(self, db, message, exc, "send_whatsapp_template_failed", message_id)
    finally:
        db.close()


def _bad_number_reason(phone: str):
    """Why a guest's number can't be messaged, or None if it looks fine. A
    number that isn't a real one (a wrong country prefix, too many digits) is
    accepted by Meta's API and then simply never delivers -- the message sits
    at one grey tick forever."""
    from app.services.wa_subscriber_import import validate_phone
    if not (phone or "").strip():
        return "This guest has no phone number."
    _, problem = validate_phone(phone)
    if problem:
        return f"The phone number on this guest ({phone}) isn't a valid WhatsApp number. Correct it on the guest's profile, then retry."
    return None


def _template_components(db, tenant_id: str, message: Message, variables: list) -> list:
    """The full components array for a template send: the body's values in
    order, plus the header image/video/PDF when the template has one. Meta
    rejects a template message whose components don't match the template."""
    from app.api.v1.endpoints.messaging import WATemplate
    from app.services import wa_template_service as wts
    from app.services.media_storage import get_presigned_media_url

    template_id = (message.channel_metadata or {}).get("template_id")
    tmpl = db.query(WATemplate).filter_by(id=template_id, tenant_id=tenant_id).first() if template_id else None
    if tmpl is None:
        # Older messages without a stored template id: body values only, as before.
        return [{"type": "body", "parameters": [{"type": "text", "text": str(v)} for v in (variables or [])]}] if variables else []

    vmap = {"body": {str(i): {"source": "static", "value": str(v)} for i, v in enumerate(variables or [], start=1)}}
    link = get_presigned_media_url(tmpl.header_media_key, expires_in=3600) if tmpl.header_media_key else None
    return wts.build_send_components(tmpl.components, vmap, None, header_media_link=link)


def _already_sent(message) -> bool:
    """The message has a provider id and has reached SENT or later."""
    return bool(
        message.channel_message_id
        and not str(message.channel_message_id).startswith("draft_")
        and message.delivery_state in (MessageDeliveryState.SENT, MessageDeliveryState.DELIVERED, MessageDeliveryState.READ)
    )


def _phone_token(value) -> str:
    """Stable short hash for correlating log lines without writing the number."""
    import hashlib
    return hashlib.sha256(str(value or "").encode()).hexdigest()[:12]


def _fail_or_retry(task, db, message, exc: Exception, event: str, message_id: str) -> None:
    """A failed send: record Meta's real reason on the message. Retry only when
    another attempt could plausibly work; a 4xx verdict is final."""
    from app.services import wa_campaign_delivery as delivery
    reason = delivery.failure_text(exc)
    log.error(event, message_id=message_id, error=str(exc), meta_reason=reason)
    if message is None:
        raise exc
    if not delivery.is_retryable(exc) or task.request.retries >= task.max_retries:
        _mark_failed(db, message, reason)
        return
    raise task.retry(exc=exc)


def _mark_failed(db, message: Message, reason: str) -> None:
    """Transition message to FAILED and record the reason."""
    try:
        message.delivery_state = MessageDeliveryState.FAILED
        message.delivery_error = reason[:500]  # cap length
        message.channel_status = "failed"
        db.commit()
        log.warning(
            "send_whatsapp_marked_failed",
            message_id=message.id,
            reason=reason,
        )
    except Exception:
        pass  # never let cleanup crash the task
