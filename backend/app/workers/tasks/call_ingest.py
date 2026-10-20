"""
Call ingestion pipeline:
  IVR webhook → fetch recording → store S3 → queue transcription
"""
import asyncio
import boto3
from botocore.config import Config
import hashlib
import phonenumbers
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.core.config import settings
from app.models.call import Call, CallDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.conversation import Conversation, ChannelType
from app.adapters.ivr import get_ivr_adapter
from app.services import identity_service
from app.services import inquiry_service as _inquiry_service
from app.models.call import RecordingStatus
from app.workers.celery_app import celery_app
from app.core.cache import get_cached, set_cached
import structlog
import uuid
from datetime import datetime, timezone, timedelta


def _phone_token(phone: str) -> str:
    """One-way hash for log correlation without exposing PII phone numbers."""
    return hashlib.sha256(phone.encode()).hexdigest()[:12]

log = structlog.get_logger()

_RECOVERY_WINDOW_HOURS = 24

# Role-portal Phase A: Call.agent_id was never written anywhere in this
# pipeline -- every other field on the Call() below is set except this
# one. For outbound calls, the initiating agent is known at click-to-call
# time (calls.py's endpoint has current_user), but nothing carried that
# forward to the Call row this task creates minutes later from the IVR
# webhook. Cached by the provider's own call id (the only identifier both
# sides share -- calls.py's `call_id` return value is the same value the
# webhook later reports as normalized.ivr_call_id).
#
# Vobiz Dial-callback plan: this cache is no longer outbound-only despite
# its name. webhooks_vobiz.py's dial-status webhook now writes to the same
# cache for inbound calls too -- Vobiz's DialAnswer event's DialBLegTo
# (the number that actually answered) matched against a known agent's
# phone, keyed by the same call_uuid/ivr_call_id. Kept the original
# function names rather than a rename to keep this change's diff small.
_CLICK_TO_CALL_AGENT_TTL = 3600 * 2


def _click_to_call_cache_key(tenant_id: str, ivr_call_id: str) -> str:
    return f"haip:click_to_call_agent:{tenant_id}:{ivr_call_id}"


def cache_click_to_call_agent(tenant_id: str, ivr_call_id: str, agent_id: str) -> None:
    set_cached(_click_to_call_cache_key(tenant_id, ivr_call_id), agent_id, ttl=_CLICK_TO_CALL_AGENT_TTL)


def _lookup_click_to_call_agent(tenant_id: str, ivr_call_id: str) -> str | None:
    return get_cached(_click_to_call_cache_key(tenant_id, ivr_call_id))


def _link_recovered_call(db: Session, tenant_id: str, guest_id: str, outbound_call: Call) -> None:
    """
    Phase 2.5 agent-accountability instrumentation
    (HAIP_Agent_Analytics_Dashboard_Plan_1.md #2.5.3): when an outbound call
    lands for a guest with an unrecovered missed inbound call in the last
    24h, link it so "did we call them back" is a query instead of
    unanswerable. "Missed" follows call_status_service -- the same rule
    calls.py's serializers use for is_missed. Matches on
    Call.created_at (real DateTime) rather than started_at/ended_at, which
    are String columns and unreliable for range comparison.
    """
    window_start = outbound_call.created_at - timedelta(hours=_RECOVERY_WINDOW_HOURS)
    # "Missed" uses the product's own rule (call_status_service), not
    # "duration == 0". On Vobiz a missed call is usually recorded with a
    # nonzero duration -- the greeting and voicemail prompt play into the
    # session recording -- so the zero-duration shortcut could not see them.
    # Measured on Ratha: 57 of 76 missed calls had a nonzero duration, and
    # not one missed call had ever been linked to its callback, including
    # the two that were genuinely returned within 24h.
    from app.services.call_status_service import missed_call_sql_filter

    missed = (
        db.query(Call)
        .filter(
            Call.tenant_id == tenant_id,
            Call.guest_id == guest_id,
            missed_call_sql_filter(),
            Call.recovered_by_call_id.is_(None),
            Call.created_at >= window_start,
            Call.created_at < outbound_call.created_at,
        )
        .order_by(Call.created_at.desc())
        .first()
    )
    if missed:
        missed.recovered_by_call_id = outbound_call.id

        # Whoever actually calls the lead back owns it -- linking the
        # recovery call alone left the missed call itself (and the lead)
        # permanently unattributed, since only the separate outbound Call
        # row carried agent_id. Propagate it backward, same "don't clobber
        # an existing signal" rule as every other attribution field.
        if outbound_call.agent_id and missed.agent_id is None:
            missed.agent_id = outbound_call.agent_id
            if missed.inquiry_id:
                inquiry = db.query(Inquiry).filter_by(id=missed.inquiry_id, tenant_id=tenant_id).first()
                if inquiry and not inquiry.assigned_to:
                    from app.services.lead_assignment_service import claim_on_first_touch
                    claim_on_first_touch(db, tenant_id, inquiry.guest_id, outbound_call.agent_id)

        db.commit()
        log.info("missed_call_recovered", missed_call_id=missed.id, recovery_call_id=outbound_call.id, agent_id=missed.agent_id)


# How long before an unanswered outbound call's reminder is "due" on My Day.
_CALLBACK_REMINDER_WINDOW = timedelta(hours=2)


def _maybe_create_callback_task(db: Session, tenant_id: str, call: Call, guest: Guest, inquiry: "Inquiry | None") -> None:
    """An agent's own outbound call that nobody picked up gets a follow-up
    Task -- confirmed live gap (Ratha, Sep 2026, "autopilot" pass):
    call_status_service.is_missed_call() is deliberately inbound-only ("we
    called, they didn't pick up" is not the same thing as "they called, we
    missed it"), so this case had no reminder anywhere; staff had to notice
    it by browsing the Calls page. Mirrors concierge_draft.py's
    _maybe_create_price_handoff/_maybe_alert_phone_decline shape: dedup on
    an open task with a matching title, real due_date, a push alert."""
    from app.models.task import Task
    from app.services.call_status_service import is_unanswered_outbound_at_ingest

    if not is_unanswered_outbound_at_ingest(call):
        return

    existing = (
        db.query(Task)
        .filter_by(tenant_id=tenant_id, guest_id=guest.id, is_done=False)
        .filter(Task.title.ilike("Call back — no answer from%"))
        .first()
    )
    if existing:
        return

    guest_label = (getattr(guest, "name", None) or "").strip() or "this lead"
    task = Task(
        tenant_id=tenant_id,
        title=f"Call back — no answer from {guest_label}",
        priority="medium",
        guest_id=guest.id,
        inquiry_id=getattr(inquiry, "id", None),
        assigned_to=call.agent_id,   # the agent who placed the call, if known
        due_date=datetime.now(timezone.utc) + _CALLBACK_REMINDER_WINDOW,
    )
    db.add(task)
    db.commit()
    log.info("callback_task_created", tenant_id=tenant_id, call_id=call.id, task_id=task.id)

    try:
        from app.services.push_service import send_to_tenant
        send_to_tenant(
            db, tenant_id,
            title="No answer on that call",
            body=f"{guest_label} didn't pick up. A callback reminder has been added.",
            url=f"/dashboard/calls?call={call.id}",
            user_id=call.agent_id or None,
        )
    except Exception as exc:
        log.warning("callback_task_push_failed", tenant_id=tenant_id, error=str(exc))


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, name="call_ingest.process")
def ingest_call(self, payload: dict, tenant_id: str, ivr_provider: str):
    """
    Main entry: parse webhook → dedup guest → create Call → fetch recording → trigger transcription.
    Idempotent: checks ivr_call_id before creating.
    """
    try:
        adapter = get_ivr_adapter(ivr_provider)
        normalized = adapter.parse_call_webhook(payload)

        from app.core.database import set_tenant_context
        db: Session = SessionLocal()
        try:
            set_tenant_context(db, tenant_id)
            # Idempotency check
            existing = db.query(Call).filter_by(
                ivr_call_id=normalized.ivr_call_id,
                tenant_id=tenant_id,
            ).first()
            if existing:
                log.info("call_already_ingested", call_id=existing.id)
                return {"call_id": existing.id, "status": "already_exists"}

            # Dedup / upsert guest by phone. Direction-aware: for an inbound
            # call from_number IS the guest, but for outbound click-to-call
            # from_number is the tenant's own IVR/DID number (see
            # VobizAdapter.initiate_click_to_call -- Vobiz dials FROM the DID
            # TO the guest) and to_number is the real lead. Using
            # from_number unconditionally here resolved every outbound call
            # to a bogus "guest" whose phone was literally the tenant's own
            # IVR number, which is also why it showed up as the displayed
            # number on the Calls page (calls.py's serializers had the same
            # bug, fixed alongside this).
            guest_number = normalized.to_number if normalized.direction == "outbound" else normalized.from_number
            guest = _dedup_guest(db, tenant_id, guest_number)

            # HAIP Inbox UI-fidelity pass, ticket 1: a guest whose only
            # touchpoint is a phone call had no Conversation row at all
            # before this -- nothing to click into anywhere in the inbox.
            _find_or_create_voice_conversation(db, tenant_id, guest)

            # HAIP Inbox full-parity pass, ticket 1: list_conversations sorts
            # by Conversation.last_message_at and previews off the latest
            # Message -- neither was ever touched by a call, so a call for a
            # guest who already has a conversation never bumped it up the
            # list or hinted a call happened. Bump it here regardless of
            # whether the conversation above is brand new or pre-existing.
            _bump_conversation_for_call(db, tenant_id, guest.id, normalized.started_at)

            # Find or create open inquiry for this guest, routed via the
            # same Leads360 auto-create taxonomy WhatsApp/Instagram use --
            # unanswered calls land on RNR, connected calls on Active.
            from app.services.inquiry_service import get_or_create_from_call
            inquiry = get_or_create_from_call(
                db, tenant_id, guest.id,
                direction=normalized.direction, answered=normalized.duration_seconds > 0,
            )

            # Create Call record
            call = Call(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                guest_id=guest.id,
                inquiry_id=inquiry.id if inquiry else None,
                # Vobiz Dial-callback plan: this cache is no longer
                # outbound-only. webhooks_vobiz.py's new dial-status
                # webhook writes to the exact same cache/key for inbound
                # calls too (the agent whose number matched Vobiz's
                # DialBLegTo), so the lookup is now attempted regardless of
                # direction -- a miss (non-Vobiz provider, or nothing
                # matched) still correctly resolves to None, unchanged from
                # before for every call this new signal doesn't reach.
                agent_id=_lookup_click_to_call_agent(tenant_id, normalized.ivr_call_id),
                ivr_provider=normalized.provider,
                ivr_call_id=normalized.ivr_call_id,
                direction=normalized.direction,
                from_number=normalized.from_number,
                to_number=normalized.to_number,
                duration_seconds=normalized.duration_seconds,
                started_at=normalized.started_at,
                ended_at=normalized.ended_at,
                recording_url_ivr=normalized.recording_url,
                ivr_dial_status=normalized.ivr_dial_status or None,
                transcription_status="pending",
                ai_score_status="pending",
            )
            db.add(call)
            db.commit()
            db.refresh(call)

            # Lead owner from the call: the agent who answered/placed it
            # claims an unowned lead (and, with "call answerer owns" on,
            # takes over a rule-assigned one nobody had contacted yet); an
            # unowned lead with no known agent gets the normal rules.
            from app.services.lead_assignment_service import on_call_logged
            on_call_logged(db, inquiry, call)
            db.commit()

            log.info("call_created", call_id=call.id, guest_token=_phone_token(guest_number))

            if normalized.direction == "outbound":
                # A callback the guest never picked up has not recovered the
                # missed call: it stays open (and gets its own reminder below).
                from app.services.call_status_service import is_unanswered_outbound_at_ingest
                if not is_unanswered_outbound_at_ingest(call):
                    _link_recovered_call(db, tenant_id, guest.id, call)
                _maybe_create_callback_task(db, tenant_id, call, guest, inquiry)

            # Lead workflows: missed call / no answer -> WhatsApp the guest (lead_playbooks.py; off unless switched on).
            from app.services.lead_playbook_engine import playbook_for_call
            if playbook_for_call(call):
                from app.workers.tasks.lead_playbooks import queue_on_call
                queue_on_call(tenant_id, call.id)

            # Queue recording fetch + transcription
            fetch_and_store_recording.delay(
                call_id=call.id,
                recording_url=normalized.recording_url,
                tenant_id=tenant_id,
                ivr_provider=ivr_provider,
            )

            return {"call_id": call.id, "status": "created"}

        finally:
            db.close()

    except Exception as exc:
        log.error("call_ingest_failed", error=str(exc), tenant_id=tenant_id)
        raise self.retry(exc=exc)


# Retry schedule for missing recordings (seconds):
#   attempt 1 failed → retry in +1 h
#   attempt 2 failed → retry in +6 h
#   attempt 3 failed → retry in +24 h
#   attempt 4 failed → permanently_missing (no further retries)
# Calls shorter than this never reach transcription/AI scoring -- too short
# to carry a real conversation (misdial, voicemail beep, an outbound leg
# that connected for a fraction of a second before hanging up).
_MIN_DURATION_FOR_AI_SECONDS = 10

_RETRY_DELAYS = [3600, 21600, 86400]   # 1 h, 6 h, 24 h
_RETRY_STATES = [
    RecordingStatus.MISSING_RETRY_1,
    RecordingStatus.MISSING_RETRY_2,
    RecordingStatus.MISSING_RETRY_3,
]


@celery_app.task(
    bind=True,
    max_retries=len(_RETRY_DELAYS),
    name="call_ingest.fetch_recording",
)
def fetch_and_store_recording(self, call_id: str, recording_url: str, tenant_id: str, ivr_provider: str):
    """Thin Celery wrapper — delegates to _do_fetch_recording for testability."""
    _do_fetch_recording(self, call_id, recording_url, tenant_id, ivr_provider)


def _do_fetch_recording(task_self, call_id: str, recording_url: str, tenant_id: str, ivr_provider: str):
    """
    Download recording from IVR provider and store in S3 / R2.

    Extracted from the Celery task so it can be unit-tested with a plain mock
    for task_self instead of fighting Celery's property descriptors.

    Retry schedule (B15):
      - Attempt 1 fails → status=missing_retry_1, retry in +1 h
      - Attempt 2 fails → status=missing_retry_2, retry in +6 h
      - Attempt 3 fails → status=missing_retry_3, retry in +24 h
      - Attempt 4 fails → status=permanently_missing — no more retries
    """
    db: Session = SessionLocal()
    try:
        call = db.query(Call).filter_by(id=call_id, tenant_id=tenant_id).first()
        if not call:
            log.error("call_not_found_for_recording_fetch", call_id=call_id)
            return

        call.recording_status = RecordingStatus.FETCHING
        db.commit()

        adapter = get_ivr_adapter(ivr_provider)
        if ivr_provider == "vobiz":
            # Vobiz is the client's own account, not a shared HAIP server
            # credential like CallerDesk/Acefone/Mcube -- fetch_recording()
            # needs this tenant's own auth_id/auth_token, not the adapter's
            # (empty) global-settings fallback.
            from app.adapters.ivr.vobiz import VobizAdapter
            from app.models.integration import Integration
            from app.core.encryption import get_credential
            integration = db.query(Integration).filter_by(tenant_id=tenant_id, kind="vobiz").first()
            if integration and integration.credentials_kms_blob:
                adapter = VobizAdapter(
                    auth_id=get_credential(integration.credentials_kms_blob, "api_key"),
                    auth_token=get_credential(integration.credentials_kms_blob, "api_secret"),
                )
        audio_bytes = asyncio.run(adapter.fetch_recording(recording_url))

        s3_key = f"{tenant_id}/calls/{call_id}/recording.mp3"
        s3_kwargs = dict(
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
        if settings.AWS_S3_ENDPOINT_URL:
            s3_kwargs["endpoint_url"] = settings.AWS_S3_ENDPOINT_URL
            # Path-style addressing -- virtual-hosted-style (boto3's default)
            # sends requests to "<bucket>.<endpoint>", which breaks TLS cert
            # validation against Cloudflare R2's endpoint (confirmed live in
            # production: SSLV3_ALERT_HANDSHAKE_FAILURE on every upload).
            s3_kwargs["config"] = Config(s3={"addressing_style": "path"})
        s3 = boto3.client("s3", **s3_kwargs)
        put_kwargs = dict(
            Bucket=settings.S3_BUCKET_NAME,
            Key=s3_key,
            Body=audio_bytes,
            ContentType="audio/mpeg",
        )
        # SSE-KMS is an AWS S3 API feature R2 doesn't implement (R2 encrypts
        # at rest by default, with no S3-API SSE parameters) -- only send it
        # against real AWS S3, i.e. when no custom endpoint is configured.
        if not settings.AWS_S3_ENDPOINT_URL:
            put_kwargs["ServerSideEncryption"] = "aws:kms"
            if settings.KMS_KEY_ID:
                put_kwargs["SSEKMSKeyId"] = settings.KMS_KEY_ID
        s3.put_object(**put_kwargs)

        call.recording_s3_key = s3_key
        call.recording_fetched = True
        call.recording_status = RecordingStatus.AVAILABLE
        call.recording_error = None

        if (call.duration_seconds or 0) < _MIN_DURATION_FOR_AI_SECONDS:
            # Too short to carry a real conversation -- typically a
            # misdial, voicemail beep, or an outbound leg that connected
            # for a fraction of a second before hanging up. Not worth a
            # transcription/scoring API call, and previously these sat at
            # transcription_status="queued" forever since nothing ever
            # dequeued them.
            call.transcription_status = "skipped_short_call"
            call.ai_score_status = "skipped_short_call"
            db.commit()
            log.info("recording_stored_call_too_short_for_ai", call_id=call_id, duration_seconds=call.duration_seconds)
        elif settings.TRANSCRIPTION_PAUSED:
            call.transcription_status = "pending"
            db.commit()
            log.info("recording_stored_transcription_paused", call_id=call_id, s3_key=s3_key)
        else:
            call.transcription_status = "queued"
            db.commit()

            log.info("recording_stored", call_id=call_id, s3_key=s3_key)

            from app.workers.tasks.transcribe import transcribe as transcribe_new
            transcribe_new.delay(call_id=call_id, tenant_id=tenant_id)

    except Exception as exc:
        error_str = str(exc)
        retry_index = task_self.request.retries  # 0-based

        if retry_index < len(_RETRY_DELAYS):
            new_status = _RETRY_STATES[retry_index]
            delay = _RETRY_DELAYS[retry_index]
            log.warning(
                "recording_fetch_failed_will_retry",
                call_id=call_id,
                attempt=retry_index + 1,
                next_status=new_status.value,
                retry_in_seconds=delay,
                error=error_str,
            )
            _mark_recording_status(db, call, new_status, error_str)
            raise task_self.retry(exc=exc, countdown=delay)
        else:
            log.error("recording_permanently_missing", call_id=call_id, error=error_str)
            _mark_recording_status(db, call, RecordingStatus.PERMANENTLY_MISSING, error_str)

    finally:
        db.close()


def _mark_recording_status(db, call: Call, status: RecordingStatus, error: str) -> None:
    """Persist recording_status + error; never raises."""
    try:
        call.recording_status = status
        call.recording_error = error[:500]
        db.commit()
    except Exception:
        pass


def _dedup_guest(db: Session, tenant_id: str, phone: str) -> Guest:
    """Resolve the calling phone number to a GID via identity_service --
    the only place guest identity resolution is allowed to happen (see
    CLAUDE.md). Previously this hardcoded a new Guest with name="Unknown
    Guest" and a direct phone= lookup, bypassing identity_service entirely
    and permanently stamping "Unknown Guest" even when other signals for
    the same guest already existed."""
    try:
        parsed = phonenumbers.parse(phone, "IN")
        e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        e164 = phone

    guest_id, _created = identity_service.resolve_gid(
        db, tenant_id, signal_type="phone", value=e164, source="ivr_call",
    )
    return db.query(Guest).filter_by(id=guest_id).one()


def _find_or_create_voice_conversation(db: Session, tenant_id: str, guest: Guest) -> "Conversation | None":
    """
    HAIP Inbox UI-fidelity pass, ticket 1. The inbox's left-panel list only
    ever queries the Conversation table (see conversations.py::list_conversations)
    -- a guest whose only touchpoint is a phone call never got one, so they
    were invisible in the inbox no matter which conversation you opened.

    Only creates a channel=voice Conversation when the guest has ZERO
    conversations of any channel yet -- once a real WhatsApp/Instagram
    thread exists (even later), that's the conversation the call shows up
    inside via the merged timeline (GET /conversations/{id}/timeline);
    this fallback only covers the gap before that happens. Checked before
    create (not per-call), so this is idempotent across repeat calls from
    the same guest.
    """
    existing = db.query(Conversation.id).filter_by(tenant_id=tenant_id, guest_id=guest.id).first()
    if existing:
        return None

    conv = Conversation(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        guest_id=guest.id,
        channel=ChannelType.VOICE,
        is_open=True,
    )
    db.add(conv)
    db.commit()
    log.info("voice_conversation_created", conversation_id=conv.id, tenant_id=tenant_id)
    return conv


def _bump_conversation_for_call(db: Session, tenant_id: str, guest_id: str, call_started_at: str) -> None:
    """HAIP Inbox full-parity pass, ticket 1: nothing in the call pipeline
    ever touched Conversation.last_message_at, which is exactly what
    list_conversations sorts by -- a call for a guest who already has a
    conversation (WA/IG/voice) never bumped it up the list. Fires
    unconditionally, after _find_or_create_voice_conversation has already
    guaranteed a conversation row exists for this guest one way or another.
    Timestamp-only; the list preview text itself is derived separately in
    list_conversations by comparing this against the latest Message."""
    conv = db.query(Conversation).filter_by(tenant_id=tenant_id, guest_id=guest_id).first()
    if not conv:
        return
    conv.last_message_at = call_started_at or datetime.now(timezone.utc).isoformat()
    db.commit()


def _find_or_create_inquiry(db: Session, tenant_id: str, guest: Guest) -> Inquiry:
    """Find the most recent open inquiry for guest, or create new."""
    inquiry = (
        db.query(Inquiry)
        .filter_by(tenant_id=tenant_id, guest_id=guest.id)
        .filter(Inquiry.stage.not_in([InquiryStage.BOOKED, InquiryStage.LOST, InquiryStage.GHOSTED]))
        .order_by(Inquiry.created_at.desc())
        .first()
    )

    if not inquiry:
        inquiry = Inquiry(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            guest_id=guest.id,
            stage=InquiryStage.NEW,
            stage_id=_inquiry_service._stage_id_for(db, tenant_id, InquiryStage.NEW),
            source=InquirySource.PHONE,
        )
        db.add(inquiry)
        db.flush()

    return inquiry
