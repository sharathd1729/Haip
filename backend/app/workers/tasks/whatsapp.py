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


# Things a guest does that aren't a question for the concierge to answer.
_NO_AI_TYPES = {"reaction", "sticker", "system", "unsupported", "unknown", "request_welcome"}


def _describe_other_message(msg_type: str, msg: dict) -> str:
    """Readable text for every inbound type that isn't plain text or media.

    Real case (Ratha, Sep 2026): guests answering a broadcast showed up as
    blank bubbles and got no AI reply. Only "text" and "interactive" were
    read; a tap on a template's quick-reply button arrives as type "button",
    and reactions, stickers, locations and shared contacts all arrived with
    no text at all."""
    if msg_type == "button":                                   # quick-reply on a template
        b = msg.get("button") or {}
        return str(b.get("text") or b.get("payload") or "")
    if msg_type == "interactive":                              # reply to an interactive message
        i = msg.get("interactive") or {}
        r = i.get("button_reply") or i.get("list_reply") or {}
        return str(r.get("title") or "")
    if msg_type == "reaction":
        emoji = (msg.get("reaction") or {}).get("emoji")
        return f"{emoji} Reacted to a message" if emoji else "Removed a reaction"
    if msg_type == "sticker":
        return "[Sticker]"
    if msg_type == "location":
        loc = msg.get("location") or {}
        label = " · ".join(str(x) for x in (loc.get("name"), loc.get("address")) if x)
        return f"📍 Shared a location{': ' + label if label else ''} ({loc.get('latitude')}, {loc.get('longitude')})"
    if msg_type == "contacts":
        names = [str(((c.get("name") or {}).get("formatted_name")) or "") for c in msg.get("contacts") or []]
        return "👤 Shared a contact" + (f": {', '.join(n for n in names if n)}" if any(names) else "")
    if msg_type == "order":
        return "🛒 Sent an order"
    return f"[{msg_type or 'unknown'} message — this type can't be shown here]"


def _handle_inbound_message(db, tenant: Tenant, msg: dict, contacts: list):
    from_number = "+" + msg.get("from", "").lstrip("+")
    wa_msg_id = msg.get("id", "")
    msg_type = msg.get("type", "text")
    # Click-to-WhatsApp ad attribution -- Meta sends this once, on the
    # thread's first inbound message only (Dashboard Metrics Plan Phase 1).
    referral = msg.get("referral")

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
            # Inherit the tenant's WhatsApp policy (migration 079) rather than
            # a hardcoded "shadow", matching how the Instagram path already
            # inherits ig_ai_mode_default. The effective mode is re-resolved
            # per message in ai_mode_service, so this is only the initial
            # snapshot -- but it must not contradict the tenant's setting.
            ai_mode=(tenant.wa_ai_mode_default or "shadow"),
        )
        # Real bug, reported live on the Instagram side of this exact
        # pattern: two webhook deliveries for the same guest arriving
        # milliseconds apart both see "no open conversation" above and both
        # try to create one, splitting the guest's messages across two
        # "twin" conversations -- see migration 099 and
        # process_instagram_dm.py's identical fix for the full story
        # (confirmed root cause of a lead's travel dates silently never
        # reaching generate_ai_summary.py). A SAVEPOINT, not a full
        # db.rollback(), so losing this race only undoes the conversation
        # insert, not anything RLS-scoped or already-committed earlier in
        # this task.
        try:
            with db.begin_nested():
                db.add(conversation)
                db.flush()
        except IntegrityError:
            conversation = (
                db.query(Conversation)
                .filter_by(tenant_id=tenant.id, guest_id=guest_id, channel=ChannelType.WHATSAPP, is_open=True)
                .first()
            )
            is_new_conversation = False
            if conversation is None:
                raise
    if conversation.is_personal_bridge:
        # The guest's one open WhatsApp thread was mirrored from the agent's personal phone, and now they have written to the
        # official number: from here on it is an official thread (the concierge and the inbox may answer it). Personal-phone
        # messages that still arrive in it are skipped by the reply safety net, message by message.
        conversation.source = None
        log.info("wa_personal_bridge_thread_became_official", conversation_id=conversation.id, tenant_id=tenant.id)

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
    else:
        body = _describe_other_message(msg_type, msg)

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

    # Click-to-WhatsApp ad attribution -- captured once, on the thread's
    # first inbound message (Dashboard Metrics Plan Phase 1). source_id is
    # the ad/post id per Meta's referral object; there is no adset/campaign
    # id on the referral itself, resolved later by joining ad_id against
    # ad_metrics (Phase 3).
    if referral:
        try:
            from app.services.attribution_service import record_referral_attribution
            record_referral_attribution(
                db, tenant.id,
                conversation_id=conversation.id,
                guest_id=guest_id,
                destination_channel="whatsapp",
                ad_id=referral.get("source_id"),
                source_type=referral.get("source_type"),
                source_url=referral.get("source_url"),
                headline=referral.get("headline"),
                media_type=referral.get("media_type"),
                ctwa_clid=referral.get("ctwa_clid"),
                raw_referral=referral,
                first_message_at=message.created_at,
            )
        except Exception as exc:
            log.warning("wa_attribution_capture_failed", tenant_id=tenant.id, error=str(exc))

    # Leads360 chat auto-create. Real bug, reported live on the Instagram
    # side of this identical pattern: gating on is_new_conversation (true
    # exactly once, on the literal first message) meant a guest whose
    # opener had an empty body (a pure media/document forward, no caption)
    # never got an inquiry created -- not then, not on any later message
    # either, since is_new_conversation is permanently False after that
    # first message. Gating on "no inquiry yet" instead retries on every
    # message until one qualifies, and conversation.inquiry_id being set
    # the first time this fires still guarantees it only ever creates one
    # (identity_service already dedupes the guest; this dedupes the
    # inquiry).
    if not conversation.inquiry_id and body:
        try:
            from app.services.inquiry_service import get_or_create_from_chat
            from app.models.inquiry import InquirySource
            # A referral-bearing first message is an ad-attributed lead, not
            # a direct WA_DIRECT inbound -- previously always WA_DIRECT,
            # which made Click-to-WhatsApp leads indistinguishable from
            # organic ones anywhere inquiries.source is read.
            lead_source = InquirySource.CLICK_TO_WA.value if referral else InquirySource.WA_DIRECT.value
            lead_inquiry = get_or_create_from_chat(
                db, tenant.id, guest_id, source=lead_source, message_text=body,
            )
            conversation.inquiry_id = lead_inquiry.id
            db.flush()
            if referral:
                from app.services.attribution_service import link_attribution_to_inquiry
                link_attribution_to_inquiry(db, tenant.id, conversation.id, lead_inquiry.id)
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

    # ── Lead workflows: "Call me back" on one of our missed-call / no-answer WhatsApps ──
    # A callback task + a short "we'll call you" reply (lead_playbooks.on_callback_tap) instead of an AI answer.
    try:
        from app.services.lead_playbook_engine import is_callback_tap
        context_wamid = (msg.get("context") or {}).get("id")
        if is_callback_tap(db, tenant.id, msg_type, body.strip(), context_wamid):
            message.automation_outcome = "playbook_callback_requested"
            db.commit()
            from app.workers.tasks.lead_playbooks import on_callback_tap
            on_callback_tap.apply_async(kwargs={"tenant_id": tenant.id, "guest_id": guest.id, "inquiry_id": conversation.inquiry_id,
                                                "wa_msg_id": wa_msg_id, "button_text": body.strip()}, countdown=2)
            return
    except Exception as exc:  # noqa: BLE001 -- fall through to the normal AI reply
        log.warning("playbook_callback_tap_failed", tenant_id=tenant.id, error=str(exc)[:200])

    # ── Trigger AI Concierge ───────────────────────────────────────────────
    # Only trigger for text/interactive messages (not raw media without caption)
    # Phase 2.5 agent-accountability instrumentation
    # (HAIP_Agent_Analytics_Dashboard_Plan_1.md #2.5.2): WhatsApp has no
    # keyword-rule engine (that's Instagram-only, ig_keyword_match.py), so
    # every inbound message here is effectively "no_match" -- outcome is
    # just AI-drafted vs no response, same vocabulary as the IG side so
    # downstream queries don't need a per-channel case split.
    if body and body.strip() and msg_type not in _NO_AI_TYPES:
        try:
            from app.workers.tasks.concierge_draft import concierge_draft
            from app.services.concierge_service import mark_pending_draft, DEBOUNCE_SECONDS
            # Message-burst debounce: mark this message as the latest for
            # the conversation before queueing, with a delay long enough
            # to catch a guest's rapid-fire follow-up, so a burst produces
            # one combined draft instead of one disjointed reply per
            # message (see concierge_service.py).
            mark_pending_draft(tenant.id, conversation.id, message.id)
            concierge_draft.apply_async(
                kwargs={
                    "message_id": message.id,
                    "conversation_id": conversation.id,
                    "tenant_id": tenant.id,
                },
                countdown=DEBOUNCE_SECONDS,
            )
            log.info(
                "concierge_draft_queued",
                message_id=message.id,
                conversation=conversation.id,
            )
            message.automation_outcome = "no_match_ai_drafted"
        except Exception as exc:
            log.error("failed_to_queue_concierge_draft", error=str(exc))
            message.automation_outcome = "no_match_no_response"
    else:
        message.automation_outcome = "no_match_no_response"
    db.commit()


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
        # Not an inbox message. A message sent by a campaign has no Message
        # row: its status goes to the campaign's per-recipient record (and the
        # campaign's delivered/read counters).
        from app.services import wa_campaign_delivery
        if wa_campaign_delivery.apply_status_callback(db, str(tenant.id), status_obj):
            return
        log.warning(
            "wa_status_update_no_message",
            wamid=wamid,
            status=meta_status,
        )
        return

    # A campaign message shown in the inbox is also a row in the campaign's
    # report: keep both in step.
    meta = message.channel_metadata
    if isinstance(meta, dict) and meta.get("campaign_id"):
        from app.services import wa_campaign_delivery
        wa_campaign_delivery.apply_status_callback(db, str(tenant.id), status_obj)

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
        if isinstance(meta, dict) and meta.get("source") == "quote":   # lead journey: proposal delivered / read
            try:
                from app.services.lead_journey_tracker import on_message_status
                with db.begin_nested():
                    on_message_status(db, str(tenant.id), message, meta_status)
            except Exception as exc:  # noqa: BLE001 -- tracking must never lose the delivery update
                log.warning("journey_quote_status_failed", message_id=message.id, error=str(exc)[:200])
