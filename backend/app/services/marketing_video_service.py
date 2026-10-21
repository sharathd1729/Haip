"""AI video clips for Marketing Studio (agency M2b), via the workspace's own Higgsfield account (adapters/video.py).

  * Opt-in per workspace (brand_config.marketing_studio.video_enabled, owner) with a monthly cap in seconds of video
    (video_monthly_seconds, default 60); failed jobs don't count. Each workspace's own Higgsfield key is used, so
    the cost lands on their Higgsfield bill; HAIP records the seconds in usage_events.
  * Inputs are the workspace's own ACTIVE library photos (never a people photo without consent), sent as short-lived
    presigned URLs. No audio is generated.
  * The clip is stored as a media asset (video/mp4, source "ai", status pending_review): like AI images it is
    unusable until someone with marketing.approve approves it. Posting reels comes with a later phase.
  * Submit once (Idempotency-Key = the job's key, request id saved at once), then poll the authenticated status URL
    every POLL_SECONDS up to MAX_POLLS; webhooks are unsigned so they are not used.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.adapters import video as video_api
from app.core.audit import append_audit
from app.core.encryption import decrypt_credentials, encrypt_credentials
from app.models.integration import Integration
from app.models.marketing import MarketingCreativeJob
from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.services import media_library_service as library
from app.services import usage_service
from app.services.marketing_content_service import MarketingError
from app.services.marketing_vision import needs_consent

log = structlog.get_logger()

KIND = "higgsfield"
SETTINGS_KEY = "marketing_studio"
DEFAULT_MONTHLY_SECONDS = 60
MAX_MONTHLY_SECONDS = 1200
POLL_SECONDS = 30
MAX_POLLS = 40                     # about 20 minutes


def _section(tenant: Tenant) -> dict:
    cfg = (tenant.brand_config or {}).get(SETTINGS_KEY) if tenant is not None else None
    return dict(cfg) if isinstance(cfg, dict) else {}


def settings_of(tenant: Tenant) -> dict:
    sec = _section(tenant)
    secs = sec.get("video_monthly_seconds")
    return {"enabled": bool(sec.get("video_enabled")),
            "monthly_seconds": secs if isinstance(secs, int) and 0 <= secs <= MAX_MONTHLY_SECONDS else DEFAULT_MONTHLY_SECONDS}


def update_settings(db: Session, tenant: Tenant, actor_id: str, *, enabled: Optional[bool] = None,
                    monthly_seconds: Optional[int] = None) -> dict:
    before = settings_of(tenant)
    if monthly_seconds is not None and not 0 <= monthly_seconds <= MAX_MONTHLY_SECONDS:
        raise MarketingError(422, "bad_cap", f"The monthly limit must be 0 to {MAX_MONTHLY_SECONDS} seconds.")
    cfg = dict(tenant.brand_config or {})
    sec = _section(tenant)
    if enabled is not None:
        sec["video_enabled"] = bool(enabled)
    if monthly_seconds is not None:
        sec["video_monthly_seconds"] = monthly_seconds
    cfg[SETTINGS_KEY] = sec
    tenant.brand_config = cfg
    flag_modified(tenant, "brand_config")
    after = settings_of(tenant)
    append_audit(db, tenant_id=tenant.id, action="marketing.video.settings", actor_user_id=actor_id, target_type="tenant",
                 target_id=tenant.id, payload={"before": before, "after": after})
    return after


def connection(db: Session, tenant_id: str) -> Optional[Integration]:
    return db.query(Integration).filter_by(tenant_id=tenant_id, kind=KIND, status="active").first()


def connect(db: Session, tenant_id: str, key_id: str, key_secret: str, actor_id: str) -> Integration:
    key_id, key_secret = (key_id or "").strip(), (key_secret or "").strip()
    if not (8 <= len(key_id) <= 200 and 8 <= len(key_secret) <= 400):
        raise MarketingError(422, "bad_key", "Paste the key id and secret from your Higgsfield Cloud account.")
    integ = connection(db, tenant_id) or Integration(tenant_id=tenant_id, kind=KIND)
    integ.status = "active"
    integ.credentials_kms_blob = encrypt_credentials({"key_id": key_id, "key_secret": key_secret})
    integ.config = {"key_hint": key_id[:4] + "…" + key_id[-2:]}
    db.add(integ)
    db.flush()
    append_audit(db, tenant_id=tenant_id, action="marketing.higgsfield.connected", actor_user_id=actor_id,
                 target_type="integration", target_id=integ.id, payload={"key_hint": integ.config["key_hint"]})
    return integ


def disconnect(db: Session, tenant_id: str, actor_id: str) -> bool:
    integ = connection(db, tenant_id)
    if integ is None:
        return False
    integ.status, integ.credentials_kms_blob = "disconnected", None
    append_audit(db, tenant_id=tenant_id, action="marketing.higgsfield.disconnected", actor_user_id=actor_id,
                 target_type="integration", target_id=integ.id, payload={})
    return True


def used_seconds(db: Session, tenant_id: str) -> int:
    start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = (db.query(MarketingCreativeJob.inputs)
            .filter(MarketingCreativeJob.tenant_id == tenant_id, MarketingCreativeJob.provider == KIND,
                    MarketingCreativeJob.status != "failed", MarketingCreativeJob.created_at >= start).all())
    return sum(int((r[0] or {}).get("duration") or 0) for r in rows)


def request_video(db: Session, tenant: Tenant, asset_ids: list[str], prompt: str, duration: int, actor_id: str,
                  model_key: Optional[str] = None) -> MarketingCreativeJob:
    s = settings_of(tenant)
    if not s["enabled"]:
        raise MarketingError(409, "video_off", "AI video is switched off for this workspace (owner setting).")
    if connection(db, tenant.id) is None:
        raise MarketingError(409, "higgsfield_not_connected", "Connect Higgsfield first.")
    try:
        model = video_api.get_model(model_key)
    except video_api.VideoError as exc:
        raise MarketingError(422, "video_model_unavailable", str(exc))
    if duration not in model.durations:
        raise MarketingError(422, "bad_duration", f"Length must be one of {', '.join(map(str, model.durations))} seconds.")
    ids = list(dict.fromkeys(asset_ids))
    if not 1 <= len(ids) <= model.max_images:
        raise MarketingError(422, "bad_photos", f"Pick 1 to {model.max_images} photos.")
    assets = db.query(MediaAsset).filter(MediaAsset.tenant_id == tenant.id, MediaAsset.id.in_(ids),
                                         MediaAsset.status == "active", MediaAsset.mime_type.like("image/%")).all()
    if len(assets) != len(ids):
        raise MarketingError(422, "photo_unavailable", "Use approved photos from this workspace's library.")
    if any(needs_consent(a) for a in assets):
        raise MarketingError(422, "people_consent", "A chosen photo shows people who haven't been confirmed as OK to post.")
    if used_seconds(db, tenant.id) + duration > s["monthly_seconds"]:
        raise MarketingError(409, "video_cap_reached", f"This month's {s['monthly_seconds']} seconds of AI video are used.")
    prompt = (prompt or "").strip()
    if not 3 <= len(prompt) <= 1000:
        raise MarketingError(422, "bad_prompt", "Describe the movement you want in 3 to 1,000 characters.")
    job = MarketingCreativeJob(tenant_id=tenant.id, provider=KIND, kind="video", idempotency_key=uuid.uuid4().hex,
                               inputs={"model": model.key, "asset_ids": ids, "prompt": prompt, "duration": duration},
                               created_by=actor_id)
    db.add(job)
    db.flush()
    append_audit(db, tenant_id=tenant.id, action="marketing.video.requested", actor_user_id=actor_id,
                 target_type="marketing_creative_job", target_id=job.id, payload={"duration": duration, "photos": len(ids)})
    return job


def _client(db: Session, tenant_id: str, http=None) -> video_api.Higgsfield:
    integ = connection(db, tenant_id)
    creds = decrypt_credentials(integ.credentials_kms_blob) if integ and integ.credentials_kms_blob else {}
    return video_api.Higgsfield(creds.get("key_id", ""), creds.get("key_secret", ""), client=http)


def submit(db: Session, tenant: Tenant, job_id: str, *, http=None, url_for=None) -> MarketingCreativeJob:
    """Send the job (once). Raises VideoError when transient; a permanent failure is recorded on the job."""
    from app.services.media_storage import get_presigned_media_url
    job = db.query(MarketingCreativeJob).filter_by(id=job_id, tenant_id=tenant.id).one()
    if job.external_id or job.status in ("ready", "failed"):
        return job
    model = video_api.get_model(job.inputs.get("model"))
    assets = {a.id: a for a in db.query(MediaAsset).filter(MediaAsset.tenant_id == tenant.id,
                                                          MediaAsset.id.in_(job.inputs["asset_ids"]))}
    urls = [(url_for or (lambda a: get_presigned_media_url(a.storage_key, expires_in=3600)))(assets[i])
            for i in job.inputs["asset_ids"] if i in assets]
    api = _client(db, tenant.id, http)
    try:
        job.external_id = api.submit(model, urls, job.inputs["prompt"], int(job.inputs["duration"]), job.idempotency_key)
        job.status = "running"
    except video_api.VideoError as exc:
        if exc.transient:
            raise
        job.status, job.error = "failed", str(exc)[:2000]
    finally:
        api.close()
    return job


def poll(db: Session, tenant: Tenant, job_id: str, *, http=None) -> MarketingCreativeJob:
    """Check once. Returns the job; status stays "running" while Higgsfield is still working."""
    job = db.query(MarketingCreativeJob).filter_by(id=job_id, tenant_id=tenant.id).one()
    if job.status != "running" or not job.external_id:
        return job
    job.polls = (job.polls or 0) + 1
    api = _client(db, tenant.id, http)
    try:
        st = api.status(job.external_id)
        if st["status"] == "completed" and st.get("video_url"):
            raw = api.download(st["video_url"])
        elif st["status"] in video_api.TERMINAL:
            job.status = "failed"
            job.error = {"nsfw": "Higgsfield's content check rejected this.", "canceled": "The request was cancelled."}.get(
                st["status"], f"Higgsfield could not make the video: {st.get('error') or st['status']}")[:2000]
            return job
        else:
            if job.polls >= MAX_POLLS:
                job.status, job.error = "failed", "Higgsfield did not finish within 20 minutes."
            return job
    except video_api.VideoError as exc:
        if exc.transient and job.polls < MAX_POLLS:
            return job
        job.status, job.error = "failed", str(exc)[:2000]
        return job
    finally:
        api.close()
    asset = library._store(db, tenant.id, raw, "video/mp4", "mp4", (1080, 1920), source="ai", actor_id=job.created_by,
                           alt_text=None, property_id=None, status="pending_review",
                           provenance={"provider": KIND, "model": job.inputs.get("model"), "prompt": job.inputs.get("prompt"),
                                       "duration": job.inputs.get("duration"), "from_asset_ids": job.inputs.get("asset_ids"),
                                       "request_id": job.external_id})
    job.status, job.asset_id, job.error = "ready", asset.id, None
    usage_service.record(db, tenant.id, module="marketing_studio", kind="video_seconds", units=int(job.inputs["duration"]),
                         provider=KIND, model=job.inputs.get("model"), ref_type="marketing_creative_job", ref_id=job.id)
    return job


def recent_jobs(db: Session, tenant_id: str, limit: int = 20) -> list[dict]:
    rows = (db.query(MarketingCreativeJob).filter_by(tenant_id=tenant_id)
            .order_by(MarketingCreativeJob.created_at.desc()).limit(limit).all())
    return [{"id": j.id, "provider": j.provider, "kind": j.kind, "status": j.status, "error": j.error,
             "asset_id": j.asset_id, "external_url": j.external_url, "content_id": j.content_id,
             "duration": (j.inputs or {}).get("duration"), "created_at": j.created_at} for j in rows]
