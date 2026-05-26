"""
Call ingestion pipeline:
  IVR webhook → fetch recording → store S3 → queue transcription
"""
import asyncio
import boto3
import hashlib
import phonenumbers
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.core.config import settings
from app.models.call import Call
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.adapters.ivr import get_ivr_adapter
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

        db: Session = SessionLocal()
        try:
            # Idempotency check
            existing = db.query(Call).filter_by(
                ivr_call_id=normalized.ivr_call_id,
                tenant_id=tenant_id,
            ).first()
            if existing:
                log.info("call_already_ingested", call_id=existing.id)
                return {"call_id": existing.id, "status": "already_exists"}

            # Dedup / upsert guest by phone
            guest = _dedup_guest(db, tenant_id, normalized.from_number)

            # Find or create open inquiry for this guest
            inquiry = _find_or_create_inquiry(db, tenant_id, guest)

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

            log.info("call_created", call_id=call.id, guest_token=_phone_token(normalized.from_number))

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
        audio_bytes = asyncio.run(adapter.fetch_recording(recording_url))

        s3_key = f"{tenant_id}/calls/{call_id}/recording.mp3"
        s3_kwargs = dict(
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
        if settings.AWS_S3_ENDPOINT_URL:
            s3_kwargs["endpoint_url"] = settings.AWS_S3_ENDPOINT_URL
        s3 = boto3.client("s3", **s3_kwargs)
        s3.put_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=s3_key,
            Body=audio_bytes,
            ContentType="audio/mpeg",
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=settings.KMS_KEY_ID or None,
        )

        call.recording_s3_key = s3_key
        call.recording_fetched = True
        call.recording_status = RecordingStatus.AVAILABLE
        call.recording_error = None
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
    """Find existing guest by E.164 phone or create new."""
    try:
        parsed = phonenumbers.parse(phone, "IN")
        e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        e164 = phone

    guest = db.query(Guest).filter_by(tenant_id=tenant_id, phone=e164).first()
    if not guest:
        guest = Guest(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            phone=e164,
            name="Unknown Guest",
        )
        db.add(guest)
        db.flush()

    return guest


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
