from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
from pathlib import Path
import mimetypes
import os
import uuid
import boto3
from datetime import datetime, timezone
from app.core.database import get_db
from app.core.config import settings
from app.api.v1.deps import get_current_user, get_current_user_flexible
from app.models.call import Call, CallDisposition, CallDirection
from app.models.user import User
from app.adapters.ivr import get_ivr_adapter
from pydantic import BaseModel
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/calls", tags=["calls"])

# Local upload dir used when S3 is not configured (dev / testing)
UPLOAD_DIR = Path("uploads")
ALLOWED_AUDIO_TYPES = {
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav",
    "audio/mp4", "audio/x-m4a", "audio/m4a", "audio/ogg",
    "audio/webm", "video/webm", "audio/aac", "audio/flac",
}
ALLOWED_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".webm", ".aac", ".flac"}
MAX_FILE_MB = 200


class ClickToCallRequest(BaseModel):
    guest_number: str
    agent_number: str
    inquiry_id: Optional[str] = None


class DispositionUpdate(BaseModel):
    disposition: str
    note: Optional[str] = None


@router.get("/")
def list_calls(
    page: int = 1,
    limit: int = 20,
    direction: Optional[str] = None,
    agent_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List calls for the current tenant."""
    q = db.query(Call).filter_by(tenant_id=current_user.tenant_id)

    if direction:
        q = q.filter(Call.direction == direction)
    if agent_id:
        q = q.filter(Call.agent_id == agent_id)

    total = q.count()
    calls = q.order_by(Call.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": [_serialize_call(c) for c in calls],
    }


@router.get("/{call_id}")
def get_call(call_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    call = db.query(Call).filter_by(id=call_id, tenant_id=current_user.tenant_id).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    return _serialize_call_detail(call, db)


@router.get("/{call_id}/recording")
def stream_recording(
    call_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_flexible),
):
    """
    Stream a locally stored recording (dev/testing fallback when R2 is unavailable).
    Uses flexible auth: accepts Authorization header OR ?token= query param
    so HTML <audio> elements can load the file without custom headers.
    """
    call = db.query(Call).filter_by(id=call_id, tenant_id=current_user.tenant_id).first()
    if not call or not call.recording_s3_key:
        raise HTTPException(status_code=404, detail="Recording not found")

    s3_key = call.recording_s3_key

    # Only serve if it's a local path
    if not (os.path.isabs(s3_key) or os.path.exists(s3_key)):
        raise HTTPException(status_code=404, detail="Recording is stored in cloud — use recording_url instead")

    if not os.path.exists(s3_key):
        raise HTTPException(status_code=404, detail="Recording file not found on disk")

    mime_type, _ = mimetypes.guess_type(s3_key)
    if not mime_type:
        mime_type = "audio/mpeg"

    return FileResponse(
        path=s3_key,
        media_type=mime_type,
        filename=os.path.basename(s3_key),
        headers={"Accept-Ranges": "bytes"},
    )


@router.post("/{call_id}/process")
def process_call_sync(
    call_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Run the full pipeline synchronously (no Celery required).
    Useful for dev/testing when the Celery worker isn't running.
    Steps: transcribe → classify → judge → wrap_up

    - If transcription is not done yet, run transcription first.
    - If transcription is already done, skip straight to classify/judge/wrap_up.
    - Scoring can always be re-run (e.g. if it previously failed).
    """
    call = db.query(Call).filter_by(id=call_id, tenant_id=current_user.tenant_id).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    tenant_id = current_user.tenant_id
    steps: dict = {}

    # ── Step 1: Transcription (skip if already done) ─────────────────────────
    if call.transcription_status == "done":
        steps["transcription"] = "skipped (already done)"
    else:
        try:
            from app.workers.tasks.transcribe import transcribe as transcribe_task
            result = transcribe_task.apply(kwargs={"call_id": call_id, "tenant_id": tenant_id})
            if result.failed():
                raise Exception(str(result.result))
            steps["transcription"] = "done"
        except Exception as exc:
            log.error("sync_process_transcribe_failed", call_id=call_id, error=str(exc))
            raise HTTPException(status_code=500, detail=f"Transcription error: {str(exc)}")
        db.expire(call)
        db.refresh(call)

    # ── Guard: transcript must exist before scoring ───────────────────────────
    if call.transcription_status != "done":
        raise HTTPException(
            status_code=422,
            detail=f"Transcription is not complete (status: {call.transcription_status}). Cannot score.",
        )

    # ── Steps 2-4: Classify → Judge → Wrap-up ────────────────────────────────
    # Always re-run if AI score is not done (covers failed / pending states).
    if call.ai_score_status == "done":
        steps["scoring"] = "skipped (already done)"
    else:
        try:
            from app.workers.tasks.classify import classify as classify_task
            classify_task.apply(kwargs={"call_id": call_id, "tenant_id": tenant_id})
            steps["classify"] = "done"
        except Exception as exc:
            log.warning("sync_process_classify_failed", call_id=call_id, error=str(exc))
            steps["classify"] = f"warning: {exc}"

        try:
            from app.workers.tasks.judge import judge as judge_task
            judge_task.apply(kwargs={"call_id": call_id, "tenant_id": tenant_id})
            steps["judge"] = "done"
        except Exception as exc:
            log.warning("sync_process_judge_failed", call_id=call_id, error=str(exc))
            steps["judge"] = f"warning: {exc}"

        try:
            from app.workers.tasks.wrap_up import wrap_up as wrap_up_task
            wrap_up_task.apply(kwargs={"call_id": call_id, "tenant_id": tenant_id})
            steps["wrap_up"] = "done"
        except Exception as exc:
            log.warning("sync_process_wrapup_failed", call_id=call_id, error=str(exc))
            steps["wrap_up"] = f"warning: {exc}"

    db.expire(call)
    db.refresh(call)
    return {
        "status": "done",
        "transcription_status": call.transcription_status,
        "ai_score_status": call.ai_score_status,
        "steps": steps,
        "message": "Pipeline completed.",
    }


@router.post("/upload")
async def upload_call_recording(
    file: UploadFile = File(...),
    guest_phone: str = Form("+910000000000"),
    agent_name: str = Form(""),
    direction: str = Form("inbound"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload a call recording manually (testing / import).
    Stores audio → queues full pipeline: transcribe → classify → judge → wrap_up.
    """
    from app.workers.tasks.call_ingest import _dedup_guest, _find_or_create_inquiry

    # ── Validate ──────────────────────────────────────────────────────────────
    content_type = (file.content_type or "").lower()
    ext = Path(file.filename or "recording.mp3").suffix.lower() or ".mp3"
    if content_type not in ALLOWED_AUDIO_TYPES and ext not in ALLOWED_AUDIO_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported audio format '{ext}'. Use MP3, WAV, M4A, OGG, AAC, FLAC.")

    audio_bytes = await file.read()
    size_mb = len(audio_bytes) / (1024 * 1024)
    if size_mb > MAX_FILE_MB:
        raise HTTPException(status_code=400, detail=f"File too large ({size_mb:.1f} MB). Max {MAX_FILE_MB} MB.")

    tenant_id = current_user.tenant_id
    call_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()

    # ── Guest + inquiry ───────────────────────────────────────────────────────
    guest = _dedup_guest(db, tenant_id, guest_phone or "+910000000000")
    if agent_name:
        guest.name = guest.name  # keep existing; agent name stored on call

    inquiry = _find_or_create_inquiry(db, tenant_id, guest)

    # ── Store audio ───────────────────────────────────────────────────────────
    recording_s3_key: str
    stored_locally = False

    def _store_local() -> str:
        """Save to uploads/ on disk — always works, no cloud config needed."""
        local_dir = UPLOAD_DIR / tenant_id / "calls" / call_id
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / f"recording{ext}"
        local_path.write_bytes(audio_bytes)
        log.info("upload_stored_local", call_id=call_id, path=str(local_path.resolve()))
        return str(local_path.resolve())

    if settings.AWS_ACCESS_KEY_ID:
        # Try Cloudflare R2 / S3 — fall back to local if it fails
        try:
            s3_key = f"{tenant_id}/calls/{call_id}/recording{ext}"
            s3_kwargs: dict = dict(
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
                ContentType=content_type or "audio/mpeg",
            )
            recording_s3_key = s3_key
            log.info("upload_stored_r2", call_id=call_id, key=s3_key)
        except Exception as s3_err:
            log.warning("r2_upload_failed_falling_back_to_local",
                        call_id=call_id, error=str(s3_err))
            recording_s3_key = _store_local()
            stored_locally = True
    else:
        recording_s3_key = _store_local()
        stored_locally = True

    # ── Create Call record ────────────────────────────────────────────────────
    call = Call(
        id=call_id,
        tenant_id=tenant_id,
        guest_id=guest.id,
        inquiry_id=inquiry.id if inquiry else None,
        ivr_provider="manual",
        ivr_call_id=f"manual-{call_id}",          # unique, satisfies NOT NULL constraint
        direction=CallDirection.INBOUND if direction == "inbound" else CallDirection.OUTBOUND,
        from_number=guest_phone or "+910000000000",
        to_number="manual",
        duration_seconds=0,                         # will be updated after transcription
        started_at=now_iso,
        ended_at=now_iso,
        recording_s3_key=recording_s3_key,
        recording_fetched=True,
        transcription_status="queued",
        ai_score_status="pending",
    )
    db.add(call)
    db.commit()
    db.refresh(call)

    log.info("manual_call_created", call_id=call_id, tenant=tenant_id, size_mb=round(size_mb, 2))

    # ── Queue pipeline ────────────────────────────────────────────────────────
    try:
        from app.workers.tasks.transcribe import transcribe as transcribe_task
        transcribe_task.delay(call_id=call_id, tenant_id=tenant_id)
        pipeline_status = "queued"
    except Exception as celery_err:
        # Celery/Redis not running — pipeline won't auto-start, but the Call
        # record and file are saved. User can trigger manually later.
        log.warning("celery_unavailable_pipeline_not_queued",
                    call_id=call_id, error=str(celery_err))
        pipeline_status = "saved_pipeline_offline"

    return {
        "call_id": call_id,
        "status": pipeline_status,
        "size_mb": round(size_mb, 2),
        "stored_locally": stored_locally,
        "message": (
            "Recording uploaded. Transcription + AI scoring will complete in ~60s."
            if pipeline_status == "queued"
            else "Recording saved. Start the Celery worker to process it."
        ),
    }


@router.post("/click-to-call")
async def click_to_call(
    req: ClickToCallRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger outbound call via IVR provider."""
    from app.models.tenant import Tenant
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant or not tenant.ivr_provider:
        raise HTTPException(status_code=400, detail="IVR provider not configured")

    adapter = get_ivr_adapter(tenant.ivr_provider)
    call_id = await adapter.initiate_click_to_call(req.agent_number, req.guest_number)

    log.info("click_to_call_initiated", tenant=current_user.tenant_id, call_id=call_id)
    return {"status": "initiated", "provider_call_id": call_id}


@router.patch("/{call_id}/disposition")
def update_disposition(
    call_id: str,
    req: DispositionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Human agent sets call disposition (overrides AI)."""
    call = db.query(Call).filter_by(id=call_id, tenant_id=current_user.tenant_id).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    try:
        call.human_disposition = CallDisposition(req.disposition)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid disposition: {req.disposition}")

    call.disposition_note = req.note
    call.disposition_set_by = current_user.id
    db.commit()

    return {"status": "updated", "disposition": req.disposition}


def _get_recording_url(s3_key: str | None, call_id: str | None = None) -> str | None:
    """
    Generate a presigned URL (R2/S3) or a local serve URL.
    For local files, returns /api/v1/calls/{call_id}/recording so the frontend
    can stream directly from the backend.
    """
    if not s3_key:
        return None
    # Local file path (absolute or relative that exists on disk)
    if os.path.isabs(s3_key) or os.path.exists(s3_key):
        if call_id:
            return f"/api/v1/calls/{call_id}/recording"
        return None
    # R2 / S3 — generate presigned URL valid 1 hour
    if settings.AWS_ACCESS_KEY_ID:
        try:
            s3_kwargs: dict = dict(
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION,
            )
            if settings.AWS_S3_ENDPOINT_URL:
                s3_kwargs["endpoint_url"] = settings.AWS_S3_ENDPOINT_URL
            s3 = boto3.client("s3", **s3_kwargs)
            return s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.S3_BUCKET_NAME, "Key": s3_key},
                ExpiresIn=3600,
            )
        except Exception:
            pass
    return None


def _serialize_call(call: Call) -> dict:
    """Lightweight serializer used in the list endpoint."""
    disp = call.human_disposition or call.ai_disposition
    return {
        "id": call.id,
        "direction": call.direction.value if hasattr(call.direction, "value") else call.direction,
        "from_number": call.from_number,
        "to_number": call.to_number,
        "duration_seconds": call.duration_seconds or 0,
        "started_at": call.started_at,
        "ended_at": call.ended_at,
        "guest_id": call.guest_id,
        "guest_phone": call.from_number,
        "inquiry_id": call.inquiry_id,
        "transcription_status": call.transcription_status,
        "ai_score_status": call.ai_score_status,
        "qa_score": float(call.ai_score) if call.ai_score else None,
        "ai_score": float(call.ai_score) if call.ai_score else None,
        "ai_summary": call.ai_summary,
        "disposition": disp.value if hasattr(disp, "value") else (disp or "pending"),
        "has_transcript": bool(call.transcript_json),
        "ivr_provider": call.ivr_provider,
        "created_at": call.created_at.isoformat() if call.created_at else None,
    }


def _serialize_call_detail(call: Call, db) -> dict:
    """Rich serializer for the call detail page — includes transcript, guest, score, recording URL."""
    from app.models.guest import Guest
    from app.models.transcript import Transcript
    from app.models.score import CallScore
    import json as _json

    # Guest info
    guest = db.query(Guest).filter_by(id=call.guest_id).first() if call.guest_id else None

    # Transcript — prefer Transcript table, fall back to inline JSON
    transcript_row = db.query(Transcript).filter_by(call_id=call.id).first()
    turns = []
    if transcript_row:
        raw = transcript_row.turns
        turns = _json.loads(raw) if isinstance(raw, str) else (raw or [])
    elif call.transcript_json:
        turns = call.transcript_json

    # Normalise turn keys (Transcript table uses t0/t1, legacy JSON uses start/end)
    normalised_turns = []
    for t in (turns or []):
        normalised_turns.append({
            "speaker": t.get("speaker", "unknown"),
            "text":    t.get("text", ""),
            "t0":      t.get("t0", t.get("start", 0)),
            "t1":      t.get("t1", t.get("end", 0)),
        })

    # QA score
    score_row = (
        db.query(CallScore)
        .filter_by(call_id=call.id)
        .order_by(CallScore.created_at.desc())
        .first()
    )
    score_data = None
    if score_row:
        # Reshape criterion_scores → frontend expects [{criterion, score, max_score, evidence}]
        raw_criteria = score_row.criterion_scores or []
        criteria_out = []
        for c in raw_criteria:
            criteria_out.append({
                "criterion":  c.get("id", c.get("criterion_id", c.get("name", "unknown"))),
                "score":      c.get("score", 0),
                "max_score":  c.get("max_score", 3),
                "evidence":   c.get("evidence_span", c.get("evidence", "")),
            })
        score_data = {
            "total_score":           float(score_row.total_score) if score_row.total_score else 0,
            "max_score":             float(score_row.max_score) if score_row.max_score else 100,
            "confidence":            float(score_row.ai_confidence) if score_row.ai_confidence else 0,
            "criteria":              criteria_out,
            "ai_summary":            call.ai_summary,
            "agent_strengths":       [],
            "agent_growth_areas":    [],
            "next_action":           call.ai_next_action,
            "suggested_disposition": call.ai_disposition.value if call.ai_disposition else None,
        }
    elif call.ai_score:
        # Fallback: no CallScore row but ai_score exists on call
        score_data = {
            "total_score": float(call.ai_score),
            "max_score": 100,
            "confidence": 0.9,
            "criteria": [],
            "ai_summary": call.ai_summary,
            "agent_strengths": [],
            "agent_growth_areas": [],
            "next_action": call.ai_next_action,
        }

    disp = call.human_disposition or call.ai_disposition
    recording_url = _get_recording_url(call.recording_s3_key, call_id=call.id)

    return {
        "id": call.id,
        "direction": call.direction.value if hasattr(call.direction, "value") else call.direction,
        "duration_seconds": call.duration_seconds or 0,
        "started_at": call.started_at,
        "ended_at": call.ended_at,
        "guest_id": call.guest_id,
        "guest_phone": guest.phone if guest else call.from_number,
        "guest_name": guest.name if guest else None,
        "agent_name": None,
        "inquiry_id": call.inquiry_id,
        "recording_url": recording_url,
        "recording_s3_key": call.recording_s3_key,
        "transcription_status": call.transcription_status,
        "ai_score_status": call.ai_score_status,
        "disposition": disp.value if hasattr(disp, "value") else (disp or "pending"),
        "transcript": {"turns": normalised_turns} if normalised_turns else None,
        "score": score_data,
        "ivr_provider": call.ivr_provider,
        "created_at": call.created_at.isoformat() if call.created_at else None,
        # ── Layer 2: Intent & Outcome ────────────────────────────────────────
        "layer2": {
            "occasion":               call.occasion,
            "budget_signal":          call.budget_signal,
            "decision_stage":         call.decision_stage,
            "competitor_mentioned":   call.competitor_mentioned,
            "conversion_probability": call.conversion_probability,
            "lost_reason":            call.lost_reason,
            "sentiment":              None,   # populated from classify result via score
            "detected_language":      call.detected_language,
            "is_code_mixed":          call.is_code_mixed,
        },
    }
