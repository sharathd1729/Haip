"""
Call ingestion pipeline:
  IVR webhook → fetch recording → store S3 → queue transcription
"""
import boto3
import phonenumbers
from celery import shared_task
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.core.config import settings
from app.models.call import Call
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.adapters.ivr import get_ivr_adapter
from app.workers.celery_app import celery_app
import structlog
import uuid
from datetime import datetime, timezone

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

            log.info("call_created", call_id=call.id, guest_id=guest.id)

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


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60, name="call_ingest.fetch_recording")
def fetch_and_store_recording(self, call_id: str, recording_url: str, tenant_id: str, ivr_provider: str):
    """Download recording from IVR provider and store in S3."""
    from app.workers.tasks.transcription import transcribe_call

    db: Session = SessionLocal()
    try:
        call = db.query(Call).filter_by(id=call_id, tenant_id=tenant_id).first()
        if not call:
            log.error("call_not_found", call_id=call_id)
            return

        adapter = get_ivr_adapter(ivr_provider)

        import asyncio

        def _run_async(coro):
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    raise RuntimeError
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)

        audio_bytes = _run_async(adapter.fetch_recording(recording_url))

        # Upload to S3 / Cloudflare R2
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
        call.transcription_status = "queued"
        db.commit()

        log.info("recording_stored", call_id=call_id, s3_key=s3_key)

        # Queue transcription (use new structured pipeline)
        from app.workers.tasks.transcribe import transcribe as transcribe_new
        transcribe_new.delay(call_id=call_id, tenant_id=tenant_id)

    except Exception as exc:
        log.error("recording_fetch_failed", call_id=call_id, error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()


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
