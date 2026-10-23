"""AI images for Marketing Studio: opt-in per tenant, generated in Celery, approval-gated.

Rules:
  * Off by default. Only an owner (settings.manage) switches it on: brand_config["marketing_studio"]["ai_images_enabled"].
  * Monthly cap per workspace (brand_config["marketing_studio"]["ai_images_monthly_cap"], default DEFAULT_MONTHLY_CAP,
    owner-set). Counted per calendar month in the workspace's timezone: requests that are pending or produced an image.
    Failed jobs do not count. Two requests at the same instant can overshoot the cap by one.
  * Only models enabled in adapters/image (commercial licence + confirmed endpoint). FLUX.1-dev and SD 3.5 Large are blocked.
  * The prompt goes through the same price and banned-word checks as content, and a fixed suffix keeps text, logos and
    watermarks out of the image (text belongs in the template creative, where it is checked).
  * A generated image is stored as source='ai', status='pending_review', with provider/model/prompt in provenance.
    It cannot be used in content or creatives until someone with marketing.approve approves it; nobody but the owner may
    approve an image they asked for (same rule as content, owner decision D3).
"""
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.adapters import image as image_adapter
from app.core.audit import append_audit
from app.core.prompt_versions import get_version
from app.models.marketing import MarketingImageJob
from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.models.user import User
from app.services import marketing_content_service as content_svc
from app.services import media_library_service as media
from app.services import usage_service
from app.services.marketing_content_service import MarketingError

log = structlog.get_logger()

SETTINGS_KEY = "marketing_studio"
PROMPT_SUFFIX = ", photographic, natural light, no text, no lettering, no logos, no watermark"
PROMPT_MAX = 600
DEFAULT_MONTHLY_CAP = 50          # about ₹150/month on Gemini Flash Lite Image at ~$0.034 per image
MAX_MONTHLY_CAP = 1000


def ai_images_enabled(tenant: Optional[Tenant]) -> bool:
    cfg = ((tenant.brand_config or {}).get(SETTINGS_KEY) or {}) if tenant is not None else {}
    return bool(isinstance(cfg, dict) and cfg.get("ai_images_enabled"))


def monthly_cap(tenant: Optional[Tenant]) -> int:
    cfg = ((tenant.brand_config or {}).get(SETTINGS_KEY) or {}) if tenant is not None else {}
    value = cfg.get("ai_images_monthly_cap") if isinstance(cfg, dict) else None
    return value if isinstance(value, int) and 0 <= value <= MAX_MONTHLY_CAP else DEFAULT_MONTHLY_CAP


def _month_start_utc(tenant: Tenant) -> datetime:
    try:
        tz = ZoneInfo(tenant.timezone or "Asia/Kolkata")
    except Exception:  # noqa: BLE001 -- an unknown zone name falls back to IST
        tz = ZoneInfo("Asia/Kolkata")
    local = datetime.now(tz)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def used_this_month(db: Session, tenant: Tenant) -> int:
    return (db.query(MarketingImageJob)
            .filter(MarketingImageJob.tenant_id == tenant.id, MarketingImageJob.status.in_(("pending", "ready")),
                    MarketingImageJob.created_at >= _month_start_utc(tenant))
            .count())


def set_monthly_cap(db: Session, tenant: Tenant, cap: int, actor_id: str) -> int:
    if not 0 <= cap <= MAX_MONTHLY_CAP:
        raise MarketingError(422, "bad_cap", f"The monthly cap must be between 0 and {MAX_MONTHLY_CAP}.")
    cfg = dict(tenant.brand_config or {})
    section = dict(cfg.get(SETTINGS_KEY) or {})
    before = monthly_cap(tenant)
    section["ai_images_monthly_cap"] = cap
    cfg[SETTINGS_KEY] = section
    tenant.brand_config = cfg
    flag_modified(tenant, "brand_config")
    append_audit(db, tenant_id=tenant.id, action="marketing.ai_images.cap_changed", actor_user_id=actor_id,
                 target_type="tenant", target_id=tenant.id, payload={"before": before, "after": cap})
    return cap


def set_ai_images(db: Session, tenant: Tenant, enabled: bool, actor_id: str) -> bool:
    cfg = dict(tenant.brand_config or {})
    section = dict(cfg.get(SETTINGS_KEY) or {})
    before = bool(section.get("ai_images_enabled"))
    section["ai_images_enabled"] = bool(enabled)
    cfg[SETTINGS_KEY] = section
    tenant.brand_config = cfg
    flag_modified(tenant, "brand_config")
    append_audit(db, tenant_id=tenant.id, action="marketing.ai_images.toggled", actor_user_id=actor_id,
                 target_type="tenant", target_id=tenant.id, payload={"before": before, "after": bool(enabled)})
    return bool(enabled)


def models_catalogue() -> list[dict]:
    return [{"key": m.key, "label": m.label, "enabled": m.enabled, "licence": m.licence,
             "blocked_reason": m.blocked_reason, "shapes": list(m.sizes)} for m in image_adapter.MODELS.values()]


def request_image(db: Session, tenant: Tenant, *, prompt: str, model: str, shape: str, actor_id: str,
                  seed: Optional[int] = None, content_id: Optional[str] = None) -> MarketingImageJob:
    if not ai_images_enabled(tenant):
        raise MarketingError(403, "ai_images_off", "AI images are switched off for this workspace. The owner can switch them on.")
    try:
        m = image_adapter.get_model(model)
    except image_adapter.ImageModelBlocked as exc:
        raise MarketingError(422, "model_not_allowed", str(exc))
    prompt = (prompt or "").strip()
    if not 3 <= len(prompt) <= PROMPT_MAX:
        raise MarketingError(422, "bad_prompt", f"Describe the image in 3-{PROMPT_MAX} characters.")
    if shape not in m.sizes:
        raise MarketingError(422, "bad_shape", f"{m.label} supports: {', '.join(m.sizes)}.")
    problems = content_svc.check_text(db, tenant.id, {"prompt": prompt})
    if problems:
        raise MarketingError(422, "content_not_allowed", "The description breaks a workspace rule.", problems)
    cap, used = monthly_cap(tenant), used_this_month(db, tenant)
    if used >= cap:
        raise MarketingError(429, "monthly_cap_reached",
                             f"This workspace has used {used} of its {cap} AI images this month. The owner can raise the cap.")
    job = MarketingImageJob(tenant_id=tenant.id, prompt=prompt, model=m.key, shape=shape, seed=seed, status="pending",
                            created_by=actor_id, content_id=content_id)
    db.add(job)
    db.flush()
    append_audit(db, tenant_id=tenant.id, action="marketing.ai_image.requested", actor_user_id=actor_id,
                 target_type="marketing_image_job", target_id=job.id, payload={"model": m.key, "shape": shape})
    return job


def run_image(db: Session, tenant_id: str, job_id: str) -> MarketingImageJob:
    """Called by the Celery task. Raises image_adapter.ImageGenError(transient=True) for the task to retry."""
    job = db.query(MarketingImageJob).filter_by(id=job_id, tenant_id=tenant_id).one()
    if job.status != "pending":
        return job          # idempotent: a re-delivered task does not generate twice
    tenant = db.query(Tenant).filter_by(id=tenant_id).one()
    if not ai_images_enabled(tenant):
        job.status, job.error = "failed", "AI images were switched off before this ran."
        return job
    try:
        m = image_adapter.get_model(job.model)
        raw, meta = image_adapter.generate(m, job.prompt + PROMPT_SUFFIX, job.shape, seed=job.seed)
    except image_adapter.ImageModelBlocked as exc:
        job.status, job.error = "failed", str(exc)
        return job
    except image_adapter.ImageGenError as exc:
        if exc.transient:
            raise
        job.status, job.error = "failed", str(exc)[:2000]
        return job
    try:
        asset = media.add_generated(db, tenant_id, raw, actor_id=job.created_by, provenance={
            **meta, "ai_generated": True, "prompt": job.prompt, "prompt_suffix": PROMPT_SUFFIX,
            "job_id": job.id, "prompt_version": get_version("marketing_image"), "licence": m.licence})
    except media.MediaError as exc:
        job.status, job.error = "failed", exc.message
        return job
    usage_service.record(db, tenant_id, module="marketing_studio", kind="image_gen", units=1, provider=meta.get("provider"),
                         model=m.key, input_units=meta.get("input_tokens"),
                         output_units=(meta.get("image_tokens") or 0) + (meta.get("text_tokens") or 0) or None,
                         ref_type="media_asset", ref_id=asset.id,
                         meta={"est_cost_usd": meta.get("est_cost_usd"), "image_tokens": meta.get("image_tokens")})
    job.status, job.asset_id, job.error = "ready", asset.id, None
    from app.services.marketing_agency_service import notify_needs_approval
    notify_needs_approval(db, tenant_id, "Marketing: AI image to review", "A new AI image is waiting for approval.")
    return job


def _pending_asset(db: Session, tenant_id: str, asset_id: str) -> MediaAsset:
    asset = db.query(MediaAsset).filter_by(id=asset_id, tenant_id=tenant_id).first()
    if asset is None:
        raise MarketingError(404, "asset_not_found", "No such image in this workspace.")
    return asset


def review_image(db: Session, tenant_id: str, asset_id: str, actor: User, *, approve: bool, note: Optional[str] = None) -> MediaAsset:
    asset = _pending_asset(db, tenant_id, asset_id)
    role = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
    if approve and role != "owner" and asset.created_by == actor.id:
        raise MarketingError(403, "self_approval", "You asked for this image, so someone else must approve it.")
    n = (db.query(MediaAsset)
         .filter(MediaAsset.id == asset.id, MediaAsset.tenant_id == tenant_id, MediaAsset.status == "pending_review")
         .update({"status": "active" if approve else "archived", "updated_at": datetime.now(timezone.utc)},
                 synchronize_session=False))
    if n != 1:
        raise MarketingError(409, "wrong_state", "Only an AI image waiting for review can be approved or rejected.")
    append_audit(db, tenant_id=tenant_id, action="marketing.ai_image.approved" if approve else "marketing.ai_image.rejected",
                 actor_user_id=actor.id, target_type="media_asset", target_id=asset.id, payload={"note": note, "sha256": asset.sha256})
    db.refresh(asset)
    if approve:
        attach_to_draft(db, tenant_id, asset)
    return asset


def attach_to_draft(db: Session, tenant_id: str, asset: MediaAsset) -> Optional[str]:
    """An approved AI image goes into the empty slot of the draft it was requested for (a new version). An agency draft
    that was held only for photos is then sent for approval. Returns the content id it was attached to, or None."""
    job = db.query(MarketingImageJob).filter_by(tenant_id=tenant_id, asset_id=asset.id).first()
    if job is None or not job.content_id:
        return None
    from app.services import marketing_photos as photos
    from app.services import marketing_review_service as review
    tenant = db.query(Tenant).filter_by(id=tenant_id).one()
    try:
        filled = photos.attach_photos(db, tenant, job.content_id, actor_id="agency", photos=[asset])
    except MarketingError:
        return None                       # the draft is gone or archived: the image simply stays in the library
    if not filled:
        return None
    item = content_svc.get_item(db, tenant_id, job.content_id)
    version = content_svc.get_version(db, tenant_id, item.current_version_id)
    rev = review.current(db, tenant, item)
    if (item.created_by == "agency" and item.status == "draft" and not content_svc.missing_photos(item.kind, version.payload)
            and not (rev is not None and rev.blocking)):
        from types import SimpleNamespace
        content_svc.submit(db, tenant_id, item.id, item.current_version_id, SimpleNamespace(id="agency", role="agency"))
    return item.id
