"""
Transcription task — uses TranscriptionAdapter (Groq free / Deepgram / Whisper).
Stores result in separate transcript table. Chains to classify.

Audio source resolution (in priority order):
  1. Local file path  — recording_s3_key is an absolute path on disk
                        (used for manually uploaded recordings in dev/test)
  2. S3 / R2          — standard object storage path
"""
import asyncio
import json
import os
import boto3


def _run_async(coro):
    """Run an async coroutine from a sync Celery task safely (Python 3.10+)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
from app.workers.celery_app import celery_app
from app.core.database import SessionLocal
from app.core.config import settings
from app.models.call import Call
from app.adapters.transcription import get_transcription_adapter
from app.services.transcription_service import store_transcript, redact_pii
import structlog

log = structlog.get_logger()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, name="tasks.transcribe")
def transcribe(self, call_id: str, tenant_id: str, provider: str = "deepgram"):
    from app.workers.tasks.classify import classify

    db = SessionLocal()
    try:
        call = db.query(Call).filter_by(id=call_id, tenant_id=tenant_id).first()
        if not call or not call.recording_s3_key:
            log.error("transcribe_call_not_found", call_id=call_id)
            return

        call.transcription_status = "processing"
        db.commit()

        # ── Fetch audio bytes ─────────────────────────────────────────────────
        key = call.recording_s3_key

        # Local file: absolute path or relative path that exists on disk
        if os.path.isabs(key) or os.path.exists(key):
            log.info("transcribe_reading_local", call_id=call_id, path=key)
            with open(key, "rb") as fh:
                audio_bytes = fh.read()
        else:
            # S3 / Cloudflare R2
            log.info("transcribe_reading_s3", call_id=call_id, key=key)
            s3_kwargs = dict(
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION,
            )
            if settings.AWS_S3_ENDPOINT_URL:
                s3_kwargs["endpoint_url"] = settings.AWS_S3_ENDPOINT_URL
            s3 = boto3.client("s3", **s3_kwargs)
            obj = s3.get_object(Bucket=settings.S3_BUCKET_NAME, Key=key)
            audio_bytes = obj["Body"].read()

        # Transcribe via adapter (provider auto-selected from env if not passed)
        adapter = get_transcription_adapter(provider if provider != "deepgram" else None)
        result = _run_async(adapter.transcribe(audio_bytes, language_hint="en-IN"))

        # Store in transcript table
        turns_dicts = [{"speaker": t.speaker, "t0": t.t0, "t1": t.t1, "text": t.text} for t in result.turns]
        store_transcript(
            db, call_id=call_id, tenant_id=tenant_id,
            turns=turns_dicts, raw_text=result.raw_text,
            provider=result.provider, language=result.language,
        )

        # Update call record
        call.transcription_status = "done"
        call.detected_language = result.language
        call.transcription_cost_usd = result.cost_usd
        # Keep legacy inline JSON populated for backwards compat (the canonical
        # store is the Transcript table, written above by store_transcript)
        call.transcript_json = turns_dicts
        db.commit()

        log.info("transcribe_done", call_id=call_id, turns=len(turns_dicts), provider=provider)

        # Chain: classify → judge → wrap_up (best-effort — fails gracefully if broker is down)
        try:
            classify.delay(call_id=call_id, tenant_id=tenant_id)
        except Exception as chain_exc:
            log.warning("transcribe_chain_classify_skipped", call_id=call_id, error=str(chain_exc))

    except Exception as exc:
        try:
            call.transcription_status = "failed"
            db.commit()
        except Exception:
            pass
        log.error("transcribe_failed", call_id=call_id, error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()
