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
from app.models.call import Call
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.conversation import Conversation, ChannelType
from app.adapters.ivr import get_ivr_adapter
from app.services import identity_service
from app.models.call import RecordingStatus
from app.workers.celery_app import celery_app
import structlog
import uuid
from datetime import datetime, timezone


def _phone_token(phone: str) -> str:
    """One-way hash for log correlation without exposing PII phone numbers."""
    return hashlib.sha256(phone.encode()).hexdigest()[:12]

log = structlog.get_logger()


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
                ivr_provider=normalized.provider,
                ivr_call_id=normalized.ivr_call_id,
                direction=normalized.direction,
                from_number=normalized.from_number,
                to_number=normalized.to_number,
                duration_seconds=normalized.duration_seconds,
                started_at=normalized.started_at,
                ended_at=normalized.ended_at,
                recording_url_ivr=normalized.recording_url,
                transcription_status="pending",
                ai_score_status="pending",
            )
            db.add(call)
            db.commit()
            db.refresh(call)

            log.info("call_created", call_id=call.id, guest_token=_phone_token(guest_number))

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
            source=InquirySource.PHONE,
        )
        db.add(inquiry)
        db.flush()

    return inquiry
