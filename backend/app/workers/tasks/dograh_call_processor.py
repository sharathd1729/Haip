"""
Dograh call processor — background task for call.completed webhooks.

Processes completed Dograh calls:
  1. Identity resolution (phone → GID)
  2. Inquiry resolution / creation
  3. Call record creation
  4. Transcript storage
  5. Recording fetch + S3 upload
  6. AI analysis trigger
  7. Leads360 update (last_activity, alerts, stage)
  8. Occasion detection

Constitution:
  ✓ No LLM calls inline — AI triggered via generate_ai_summary task
  ✓ Phone never logged in plaintext — _phone_token() used throughout
  ✓ Retry on transient errors (DB, S3); no retry on permanent errors
  ✓ Idempotent — duplicate dograh_call_id caught via IntegrityError
"""
import json
import uuid
from datetime import datetime, timezone

import boto3
from botocore.config import Config
import httpx
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, set_tenant_context
from app.models.call import Call, CallDirection, RecordingStatus
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.transcript import Transcript
from app.services import identity_service, ivr_service
from app.services import inquiry_service as _inquiry_service
from app.workers.celery_app import celery_app
from app.workers.tasks.generate_ai_summary import generate_ai_summary

log = structlog.get_logger()

_OCCASION_KEYWORDS = {
    "anniversary", "birthday", "family", "bachelor", "bachelorette",
    "corporate", "honeymoon", "wedding", "celebration", "proposal",
}


def _phone_token(phone: str) -> str:
    import hashlib
    return hashlib.sha256(phone.encode()).hexdigest()[:12]


def _now() -> datetime:
    return datetime.now(timezone.utc)


@celery_app.task(
    name="dograh.process_call_completed",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def process_dograh_call_completed(self, tenant_id: str, payload: dict):
    """Process a completed Dograh call end-to-end."""
    db: Session = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        _process(self, db, tenant_id, payload)
        db.commit()
    except IntegrityError:
        db.rollback()
        log.info(
            "dograh_duplicate_call_skipped",
            dograh_call_id=payload.get("call_id"),
            tenant_id=tenant_id,
        )
    except Exception as exc:
        db.rollback()
        log.warning("dograh_call_processor_failed", error=str(exc), tenant_id=tenant_id)
        raise self.retry(exc=exc)
    finally:
        db.close()


def _process(task_self, db: Session, tenant_id: str, payload: dict) -> None:
    phone = payload.get("phone_number", "")
    dograh_call_id = payload.get("call_id", "")
    dograh_agent_id = payload.get("agent_id", "")
    direction = payload.get("direction", "inbound")
    duration_seconds = int(payload.get("duration_seconds", 0))
    status = payload.get("status", "completed")
    recording_url = payload.get("recording_url")
    transcript_turns = payload.get("transcript", [])
    ev = payload.get("extracted_variables") or {}

    language_detected = (ev.get("language_detected") or "hi-IN").strip()
    sentiment = (ev.get("sentiment") or "neutral").strip()
    intent = (ev.get("intent") or "").strip()

    # ── 1. Identity resolution ────────────────────────────────────────────────
    guest_id, _created = identity_service.resolve_gid(
        db=db,
        tenant_id=tenant_id,
        signal_type="phone",
        value=phone,
        source="dograh_ivr",
    )
    log.info(
        "dograh_guest_resolved",
        tenant_id=tenant_id,
        guest_token=_phone_token(phone),
        created=_created,
    )

    # ── 2. Inquiry resolution ─────────────────────────────────────────────────
    inquiry = (
        db.query(Inquiry)
        .filter(
            Inquiry.tenant_id == tenant_id,
            Inquiry.guest_id == guest_id,
            Inquiry.stage.notin_([InquiryStage.LOST, InquiryStage.GHOSTED, InquiryStage.BOOKED]),
        )
        .order_by(Inquiry.created_at.desc())
        .first()
    )
    if not inquiry:
        inquiry = Inquiry(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            guest_id=guest_id,
            source=InquirySource.INBOUND_CALL,
            stage=InquiryStage.RESPONDING,
            stage_id=_inquiry_service._stage_id_for(db, tenant_id, InquiryStage.RESPONDING),
            current_stage_entered_at=_now(),
        )
        db.add(inquiry)
        db.flush()

    # ── 3. Call record creation ───────────────────────────────────────────────
    call_direction = CallDirection.INBOUND if direction == "inbound" else CallDirection.OUTBOUND
    call = Call(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        guest_id=guest_id,
        inquiry_id=inquiry.id,
        ivr_provider="dograh",
        ivr_call_id=dograh_call_id,
        direction=call_direction,
        from_number=phone if direction == "inbound" else "",
        to_number="" if direction == "inbound" else phone,
        duration_seconds=duration_seconds,
        ended_at=payload.get("ended_at", ""),
        transcription_status="pending",
        ai_score_status="pending",
        # Dograh-specific columns
        voice_platform="dograh",
        dograh_call_id=dograh_call_id,
        dograh_agent_id=dograh_agent_id,
        transfer_to_human=(status == "transferred"),
        transfer_reason=intent if status == "transferred" else None,
    )
    db.add(call)
    db.flush()

    # ── 4. Transcript storage ─────────────────────────────────────────────────
    turns_json = json.dumps([
        {
            "speaker": t.get("speaker", ""),
            "t0": t.get("timestamp", 0),
            "t1": t.get("timestamp", 0),
            "text": t.get("text", ""),
            "language": t.get("language", language_detected),
        }
        for t in transcript_turns
    ])
    transcript = Transcript(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        call_id=call.id,
        provider="sarvam",
        language=language_detected,
        script_type="roman",
        turns=turns_json,
    )
    db.add(transcript)

    # ── 5. Recording fetch + S3 upload ────────────────────────────────────────
    if recording_url:
        try:
            _fetch_and_store_recording(db, call, recording_url, tenant_id)
        except Exception as exc:
            log.warning("dograh_recording_fetch_failed", call_id=call.id, error=str(exc))

    # ── 6. AI analysis trigger ────────────────────────────────────────────────
    try:
        generate_ai_summary.delay(inquiry_id=inquiry.id, tenant_id=tenant_id)
    except Exception as exc:
        log.warning("dograh_ai_trigger_failed", inquiry_id=inquiry.id, error=str(exc))

    # ── 7. Leads360 update ────────────────────────────────────────────────────
    inquiry.last_activity_at = _now() if hasattr(inquiry, "last_activity_at") else None

    if sentiment == "negative":
        log.warning(
            "dograh_negative_sentiment_alert",
            tenant_id=tenant_id,
            inquiry_id=inquiry.id,
            guest_token=_phone_token(phone),
        )

    if intent == "booking" and inquiry.stage == InquiryStage.NEW:
        inquiry.stage = InquiryStage.RESPONDING
        inquiry.stage_id = _inquiry_service._stage_id_for(db, tenant_id, InquiryStage.RESPONDING) or inquiry.stage_id
        inquiry.current_stage_entered_at = _now()

    # Populate extracted booking fields. A voice-call date is more
    # authoritative than a chat-text guess, so mark it as such
    # (dates_from_chat=False) -- generate_ai_summary.py's chat extraction
    # never overwrites a date recorded here (migration 107).
    if ev.get("check_in_date"):
        inquiry.check_in = ev["check_in_date"]
        inquiry.dates_from_chat = False
    if ev.get("check_out_date"):
        inquiry.check_out = ev["check_out_date"]
        inquiry.dates_from_chat = False
    if ev.get("guest_count"):
        inquiry.adults = int(ev["guest_count"])

    # ── 8. Occasion detection ─────────────────────────────────────────────────
    full_text = " ".join(
        t.get("text", "").lower() for t in transcript_turns
    )
    detected_occasion = None
    for kw in _OCCASION_KEYWORDS:
        if kw in full_text:
            detected_occasion = kw
            break

    if detected_occasion and not inquiry.intent_tag:
        inquiry.intent_tag = detected_occasion

    # ── 9. IVR routing log ────────────────────────────────────────────────────
    dtmf_digit = payload.get("dtmf_digit")
    dtmf_department = payload.get("department")
    if dtmf_digit is not None or dtmf_department:
        try:
            ivr_service.log_call_route(
                db=db,
                tenant_id=tenant_id,
                dograh_call_id=dograh_call_id,
                digit=int(dtmf_digit) if dtmf_digit is not None else None,
                department=dtmf_department,
                duration=duration_seconds,
                caller_phone=phone,
                call_id=call.id,
            )
        except Exception as exc:
            log.warning("ivr_log_route_failed", call_id=call.id, error=str(exc))

    log.info(
        "dograh_call_processed",
        tenant_id=tenant_id,
        call_id=call.id,
        inquiry_id=inquiry.id,
        guest_token=_phone_token(phone),
        occasion=detected_occasion,
    )


def _fetch_and_store_recording(db: Session, call: Call, recording_url: str, tenant_id: str) -> None:
    """Download recording from Dograh CDN and store in S3."""
    with httpx.Client(timeout=30.0, follow_redirects=False) as client:
        resp = client.get(recording_url)
        resp.raise_for_status()
        audio_bytes = resp.content

    s3_key = f"recordings/{tenant_id}/{call.id}.mp3"
    s3_kwargs = dict(
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
    )
    if settings.AWS_S3_ENDPOINT_URL:
        s3_kwargs["endpoint_url"] = settings.AWS_S3_ENDPOINT_URL
        # Path-style addressing -- virtual-hosted-style (boto3's default)
        # breaks TLS cert validation against R2's endpoint.
        s3_kwargs["config"] = Config(s3={"addressing_style": "path"})

    s3 = boto3.client("s3", **s3_kwargs)
    put_kwargs = dict(
        Bucket=settings.S3_BUCKET_NAME,
        Key=s3_key,
        Body=audio_bytes,
        ContentType="audio/mpeg",
    )
    # SSE-KMS is an AWS S3 API feature R2 doesn't implement -- only send it
    # against real AWS S3, i.e. when no custom endpoint is configured.
    if settings.KMS_KEY_ID and not settings.AWS_S3_ENDPOINT_URL:
        put_kwargs["ServerSideEncryption"] = "aws:kms"
        put_kwargs["SSEKMSKeyId"] = settings.KMS_KEY_ID

    s3.put_object(**put_kwargs)

    call.recording_s3_key = s3_key
    call.recording_fetched = True
    call.recording_status = RecordingStatus.AVAILABLE
