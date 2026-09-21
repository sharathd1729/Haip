from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
from pathlib import Path
import hashlib
import mimetypes
import os
import uuid
import boto3
import httpx
from botocore.config import Config
from datetime import datetime, timezone
from app.core.database import get_db
from app.core.config import settings
from app.api.v1.deps import get_current_user, get_current_user_flexible
from app.models.call import Call, CallDisposition, CallDirection
from app.models.guest import Guest
from app.models.user import User
from app.adapters.ivr import get_ivr_adapter
from app.services import next_action_service, call_status_service
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


def _phone_token(phone: str) -> str:
    """One-way hash for log correlation without exposing PII phone numbers."""
    return hashlib.sha256(phone.encode()).hexdigest()[:12]


class ClickToCallRequest(BaseModel):
    guest_number: str
    # Optional override -- almost never sent by the frontend (no call site
    # passes it). Server-side default is the clicking agent's own
    # User.phone (Profile page), falling back to the tenant's shared
    # forward_number only if that agent has no phone on file at all.
    agent_number: Optional[str] = None
    inquiry_id: Optional[str] = None


class DispositionUpdate(BaseModel):
    disposition: str
    note: Optional[str] = None


class WrapUpRequest(BaseModel):
    disposition: Optional[str] = None
    notes: Optional[str] = None
    next_action: Optional[str] = None


@router.get("")
def list_calls(
    page: int = 1,
    limit: int = 20,
    direction: Optional[str] = None,
    agent_id: Optional[str] = None,
    guest_id: Optional[str] = None,
    missed: Optional[bool] = None,
    date_preset: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List calls for the current tenant.

    date_preset/date_from/date_to are optional and additive -- the main
    Calls page has never sent them (all-time list, paginated), so omitting
    them keeps that behaviour exactly as-is. Added for the Agent Profile
    page's Calls tab, which needs to scope to the selected date range.
    """
    from app.models.tenant import Tenant
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()

    q = db.query(Call).filter_by(tenant_id=current_user.tenant_id)
    # Once a tenant has a single designated active IVR provider, calls from
    # a provider that's been disconnected (e.g. Mcube, replaced by Vobiz for
    # Ratha) stay in the DB untouched but drop out of the dashboard --
    # nothing here deletes or mutates Call rows.
    if tenant and tenant.ivr_provider:
        q = q.filter(Call.ivr_provider == tenant.ivr_provider)

    if direction:
        q = q.filter(Call.direction == direction)
    if agent_id:
        q = q.filter(Call.agent_id == agent_id)
    if guest_id:
        q = q.filter(Call.guest_id == guest_id)
    # A missed call is specifically an unanswered inbound call -- see
    # _guest_facing_number's docstring for why outbound no-answers don't
    # count. Pass missed=true for the Calls page's "Missed" chip, or
    # missed=false alongside direction=inbound for "Incoming" (answered
    # inbound only).
    if missed is not None:
        q = q.filter(Call.direction == "inbound")
        if missed:
            q = q.filter(call_status_service.missed_call_sql_filter())
        else:
            q = q.filter(~call_status_service.missed_call_sql_filter())

    if date_preset or date_from or date_to:
        from app.services.date_presets import VALID_PRESETS, resolve_range, ist_range_to_utc
        preset = date_preset or "custom"
        if preset not in VALID_PRESETS:
            raise HTTPException(status_code=422, detail=f"Invalid date_preset: {preset}")
        try:
            d_from, d_to = resolve_range(preset, date_from, date_to)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid date: {exc}")
        if d_from and d_to:
            _, _, range_start_dt, range_end_dt = ist_range_to_utc(d_from, d_to)
            q = q.filter(Call.created_at >= range_start_dt, Call.created_at <= range_end_dt)

    total = q.count()
    calls = q.order_by(Call.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    guest_ids = {c.guest_id for c in calls if c.guest_id}
    guest_names = {}
    if guest_ids:
        guest_names = dict(
            db.query(Guest.id, Guest.name).filter(Guest.id.in_(guest_ids)).all()
        )

    # agent_name was hardcoded None in every serializer despite agent_id
    # being populated for outbound calls (and now inbound too, via the
    # Vobiz Dial-callback plan) -- confirmed live gap, the UI had no way
    # to show who attended a call even when the data existed.
    agent_ids = {c.agent_id for c in calls if c.agent_id}
    agent_names = {}
    if agent_ids:
        agent_names = dict(
            db.query(User.id, User.name).filter(User.id.in_(agent_ids)).all()
        )

    # "Was this missed call returned, and when?" -- one query for the page,
    # not one per row.
    recovery_ids = {c.recovered_by_call_id for c in calls if c.recovered_by_call_id}
    recovery_at = {}
    if recovery_ids:
        recovery_at = {
            rid: created.isoformat() if created else None
            for rid, created in db.query(Call.id, Call.created_at)
            .filter(Call.tenant_id == current_user.tenant_id, Call.id.in_(recovery_ids))
            .all()
        }

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": [
            _serialize_call(
                c, guest_names.get(c.guest_id), agent_names.get(c.agent_id),
                called_back_at=recovery_at.get(c.recovered_by_call_id),
            )
            for c in calls
        ],
    }


@router.get("/{call_id}")
def get_call(call_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    from app.models.tenant import Tenant
    call = db.query(Call).filter_by(id=call_id, tenant_id=current_user.tenant_id).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if tenant and tenant.ivr_provider and call.ivr_provider != tenant.ivr_provider:
        # Same as list_calls: a call from a disconnected provider stays in
        # the DB but is hidden from the dashboard -- 404, not a data error.
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
                # Path-style addressing -- virtual-hosted-style (boto3's
                # default) breaks TLS cert validation against R2's endpoint.
                s3_kwargs["config"] = Config(s3={"addressing_style": "path"})
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
    """
    Trigger outbound call via IVR provider — agent clicks a number, Vobiz
    (or whichever provider is active) rings the agent's registered mobile
    first, then bridges to the guest once picked up. No audio ever touches
    the browser; this is a provider API trigger, not a softphone.
    """
    from app.models.tenant import Tenant
    from app.models.integration import Integration
    from app.core.encryption import get_credential
    from urllib.parse import quote
    from app.adapters.ivr.vobiz import VobizAdapter

    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant or not tenant.ivr_provider:
        raise HTTPException(status_code=400, detail="IVR provider not configured")

    provider = tenant.ivr_provider.lower()

    if provider == "vobiz":
        integration = db.query(Integration).filter_by(tenant_id=tenant.id, kind="vobiz").first()
        if not integration or not integration.credentials_kms_blob:
            raise HTTPException(status_code=400, detail="Vobiz integration not configured")
        blob = integration.credentials_kms_blob
        auth_id = get_credential(blob, "api_key")
        auth_token = get_credential(blob, "api_secret")
        did_number = get_credential(blob, "did_number")
        webhook_secret = get_credential(blob, "webhook_secret")
        forward_number = get_credential(blob, "forward_number")
        # Real bug fixed here: every agent's outbound click-to-call was
        # ringing the tenant's single shared forward_number regardless of
        # who clicked -- no call site sends agent_number, and User.phone
        # (the field an agent actually edits on their Profile page) was
        # never consulted. Prefer the clicking agent's own registered
        # number; forward_number is now only the last-resort fallback for
        # an agent who hasn't set a phone at all.
        agent_number = req.agent_number or current_user.phone or forward_number
        # Real data found live: a Profile-page phone can carry a stray
        # space (e.g. "+91 8971946202") -- fine for display, but sent
        # raw into Vobiz's HTTP API `to` field it's an unvalidated string,
        # not a parsed phone number, so a malformed value there risks the
        # call routing unpredictably instead of failing loudly. Normalize
        # right before it leaves HAIP; storage/display are untouched.
        from app.services.guest_service import normalize_phone
        agent_number = normalize_phone(agent_number)
        missing = [
            name for name, val in [
                ("did_number", did_number), ("webhook_secret", webhook_secret), ("agent_number", agent_number),
            ] if not val
        ]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Vobiz outbound calling isn't fully configured yet — missing: {', '.join(missing)}. "
                       "Add these in Settings → Integrations → Vobiz.",
            )

        base = settings.API_BASE_URL.rstrip("/") if settings.API_BASE_URL else ""
        if not base:
            raise HTTPException(status_code=500, detail="API_BASE_URL not configured")
        answer_url = (
            f"{base}/api/v1/webhooks/vobiz/{tenant.slug}/{webhook_secret}"
            f"/outbound-answer?guest_number={quote(req.guest_number)}"
        )
        adapter = VobizAdapter(auth_id=auth_id, auth_token=auth_token)
        try:
            call_id = await adapter.initiate_click_to_call(
                agent_number, req.guest_number, did_number=did_number, answer_url=answer_url,
            )
        except httpx.HTTPStatusError as exc:
            # Confirmed live: Vobiz's Call API returns plain HTTP status
            # errors for account-level problems (e.g. 402 when the account
            # balance is exhausted) rather than a structured error body --
            # translate the ones we've actually seen into something an
            # agent can act on instead of a raw 500.
            status = exc.response.status_code
            if status == 402:
                detail = "Vobiz account balance is exhausted (402 from Vobiz) — top up the Vobiz account to place outbound calls."
            elif status in (401, 403):
                detail = "Vobiz rejected the account credentials (check Auth ID/Auth Secret in Settings → Integrations → Vobiz)."
            else:
                detail = f"Vobiz Call API returned {status} — could not start the call."
            log.warning("vobiz_click_to_call_http_error", tenant=current_user.tenant_id, status=status)
            raise HTTPException(status_code=502, detail=detail) from exc
    else:
        agent_number = req.agent_number or current_user.phone
        if agent_number:
            from app.services.guest_service import normalize_phone
            agent_number = normalize_phone(agent_number)
        if not agent_number:
            raise HTTPException(
                status_code=400,
                detail="No phone number on file to call from -- add one in Profile settings.",
            )
        adapter = get_ivr_adapter(provider)
        call_id = await adapter.initiate_click_to_call(agent_number, req.guest_number)

    from app.workers.tasks.call_ingest import cache_click_to_call_agent
    cache_click_to_call_agent(current_user.tenant_id, call_id, current_user.id)

    # Hashed, not raw -- but real enough to answer "did this ring the
    # clicking agent's own number or fall back?" without needing to
    # reproduce the bug live. Missing before: a real report of every
    # agent's calls ringing the tenant's shared forward_number had no log
    # trail to confirm from, since container restarts wipe prior logs and
    # click-to-call itself creates no DB row (only the later webhook does).
    log.info(
        "click_to_call_initiated",
        tenant=current_user.tenant_id, user_id=current_user.id, provider=provider,
        call_id=call_id, agent_number_token=_phone_token(agent_number),
        used_fallback_forward_number=bool(
            provider == "vobiz" and not req.agent_number and not current_user.phone
        ),
    )
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


@router.post("/{call_id}/wrap-up")
def save_wrap_up(
    call_id: str,
    req: WrapUpRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Human agent saves call wrap-up: disposition, notes, next action.
    Human disposition always overrides AI disposition.
    """
    call = db.query(Call).filter_by(id=call_id, tenant_id=current_user.tenant_id).first()
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    if req.disposition:
        try:
            call.human_disposition = CallDisposition(req.disposition)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid disposition: {req.disposition}")
        call.disposition_set_by = current_user.id

    if req.notes is not None:
        call.ai_summary = req.notes  # human notes stored in summary field (editable)

    if req.next_action is not None:
        call.ai_next_action = req.next_action

    db.commit()
    log.info("wrap_up_saved", call_id=call_id, user_id=current_user.id, disposition=req.disposition)

    return {
        "status": "saved",
        "call_id": call_id,
        "disposition": req.disposition or (call.human_disposition.value if call.human_disposition else None),
    }


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
                # Path-style addressing -- virtual-hosted-style (boto3's
                # default) breaks TLS cert validation against R2's endpoint.
                s3_kwargs["config"] = Config(s3={"addressing_style": "path"})
            s3 = boto3.client("s3", **s3_kwargs)
            return s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.S3_BUCKET_NAME, "Key": s3_key},
                ExpiresIn=3600,
            )
        except Exception:
            pass
    return None


def _guest_facing_number(call: Call) -> str:
    """The lead's own number, regardless of call direction. For outbound
    calls from_number is the tenant's own IVR/DID (Vobiz dials FROM the DID
    TO the guest) -- from_number there is never the right number to show a
    human. See call_ingest.py's _dedup_guest for the matching identity-
    resolution fix."""
    direction = call.direction.value if hasattr(call.direction, "value") else call.direction
    return call.to_number if direction == "outbound" else call.from_number


def _serialize_call(
    call: Call,
    guest_name: Optional[str] = None,
    agent_name: Optional[str] = None,
    called_back_at: Optional[str] = None,
) -> dict:
    """Lightweight serializer used in the list endpoint."""
    disp = call.human_disposition or call.ai_disposition
    direction = call.direction.value if hasattr(call.direction, "value") else call.direction
    is_missed = call_status_service.is_missed_call(call)
    return {
        "id": call.id,
        "direction": direction,
        "from_number": call.from_number,
        "to_number": call.to_number,
        "duration_seconds": call.duration_seconds or 0,
        # A missed call is specifically an inbound call nobody answered --
        # an outbound attempt that didn't connect is a failed dial, not a
        # "missed call" in the way agents mean it.
        "is_missed": is_missed,
        # Only meaningful on a missed call: did an outbound call reach this
        # guest afterwards (call_ingest._link_recovered_call). None rather
        # than False on answered calls, so the UI never shows "not called
        # back" on a call that never needed one.
        "called_back": bool(call.recovered_by_call_id) if is_missed else None,
        "called_back_at": called_back_at if is_missed else None,
        "started_at": call.started_at,
        "ended_at": call.ended_at,
        "guest_id": call.guest_id,
        "guest_name": guest_name,
        "guest_phone": _guest_facing_number(call),
        "agent_id": call.agent_id,
        "agent_name": agent_name,
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
    agent = db.query(User).filter_by(id=call.agent_id).first() if call.agent_id else None

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

    _direction = call.direction.value if hasattr(call.direction, "value") else call.direction
    return {
        "id": call.id,
        "direction": _direction,
        "duration_seconds": call.duration_seconds or 0,
        "is_missed": call_status_service.is_missed_call(call),
        "started_at": call.started_at,
        "ended_at": call.ended_at,
        "guest_id": call.guest_id,
        "guest_phone": guest.phone if guest else _guest_facing_number(call),
        "guest_name": guest.name if guest else None,
        "agent_id": call.agent_id,
        "agent_name": agent.name if agent else None,
        "inquiry_id": call.inquiry_id,
        "recording_url": recording_url,
        "recording_s3_key": call.recording_s3_key,
        "transcription_status": call.transcription_status,
        "ai_score_status": call.ai_score_status,
        "disposition": disp.value if hasattr(disp, "value") else (disp or "pending"),
        "transcript": {"turns": normalised_turns} if normalised_turns else None,
        # Flat convenience fields for simpler consumers (Calls list quick-view
        # panel) alongside the nested transcript.turns/score shapes above,
        # which the lead detail page's CallCard already relies on.
        "ai_summary": call.ai_summary,
        "ai_next_action": call.ai_next_action,
        # AI Autonomy Plan Phase 2 ticket 5: the one action contract, everywhere
        # (next_action_service.py) -- feeds AIRecommendationCard on the call
        # detail page. Replaces the old singular recommended_action field,
        # which was only ever consumed by this same page's now-removed
        # bespoke button.
        "recommended_actions": next_action_service.get_call_actions(db, call),
        "transcript_text": "\n".join(
            f"{t['speaker'].capitalize()}: {t['text']}" for t in normalised_turns
        ) if normalised_turns else None,
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
