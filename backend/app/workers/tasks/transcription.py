"""
Transcription pipeline: S3 recording → Deepgram → store transcript → queue AI scoring.
"""
import boto3
from celery import shared_task
from app.core.database import SessionLocal
from app.core.config import settings
from app.models.call import Call
from app.workers.celery_app import celery_app
import structlog

log = structlog.get_logger()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30, name="transcription.transcribe_call")
def transcribe_call(self, call_id: str, tenant_id: str):
    """Transcribe call recording using Deepgram Nova-2."""
    from app.workers.tasks.ai_scoring import score_call

    db = SessionLocal()
    try:
        call = db.query(Call).filter_by(id=call_id, tenant_id=tenant_id).first()
        if not call or not call.recording_s3_key:
            log.error("call_or_recording_not_found", call_id=call_id)
            return

        call.transcription_status = "processing"
        db.commit()

        # Fetch audio from S3
        s3 = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
        obj = s3.get_object(Bucket=settings.S3_BUCKET_NAME, Key=call.recording_s3_key)
        audio_bytes = obj["Body"].read()

        # Deepgram transcription
        transcript_data = _transcribe_with_deepgram(audio_bytes, call_id)

        # Store transcript (use transcript_json — "transcript" is now the ORM relationship)
        call.transcript_json = transcript_data["turns"]
        call.detected_language = transcript_data.get("language", "en")
        call.is_code_mixed = transcript_data.get("is_code_mixed", False)
        call.transcription_cost_usd = transcript_data.get("cost_usd", 0)
        call.transcription_status = "done"
        db.commit()

        log.info("transcription_complete", call_id=call_id, turns=len(transcript_data["turns"]))

        # Queue AI scoring
        score_call.delay(call_id=call_id, tenant_id=tenant_id)

    except Exception as exc:
        if db:
            try:
                call_obj = db.query(Call).filter_by(id=call_id).first()
                if call_obj:
                    call_obj.transcription_status = "failed"
                    db.commit()
            except Exception:
                pass
        log.error("transcription_failed", call_id=call_id, error=str(exc))
        raise self.retry(exc=exc)
    finally:
        db.close()


def _transcribe_with_deepgram(audio_bytes: bytes, call_id: str) -> dict:
    """Call Deepgram Nova-2 API with diarization."""
    from deepgram import DeepgramClient, PrerecordedOptions

    dg = DeepgramClient(api_key=settings.DEEPGRAM_API_KEY)

    options = PrerecordedOptions(
        model="nova-2",
        language="hi-en",       # Hindi + English (code-mixed)
        diarize=True,           # Speaker diarization
        punctuate=True,
        smart_format=True,
        utterances=True,
    )

    response = dg.listen.prerecorded.v("1").transcribe_file(
        {"buffer": audio_bytes, "mimetype": "audio/mpeg"},
        options,
    )

    result = response.results
    utterances = result.utterances or []

    turns = []
    for u in utterances:
        speaker = "agent" if u.speaker == 0 else "guest"
        turns.append({
            "speaker": speaker,
            "speaker_id": u.speaker,
            "text": u.transcript,
            "start": u.start,
            "end": u.end,
            "confidence": u.confidence,
        })

    # Estimate cost: ~$0.0043/min for Nova-2
    duration_min = (turns[-1]["end"] if turns else 0) / 60
    cost_usd = duration_min * 0.0043

    # Detect code-mixing (simple heuristic: check if both Devanagari and Latin chars present)
    full_text = " ".join(t["text"] for t in turns)
    has_devanagari = any("ऀ" <= c <= "ॿ" for c in full_text)
    has_latin = any("a" <= c.lower() <= "z" for c in full_text)

    return {
        "turns": turns,
        "language": "hi-en" if (has_devanagari and has_latin) else "en",
        "is_code_mixed": has_devanagari and has_latin,
        "cost_usd": cost_usd,
    }
