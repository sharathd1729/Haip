"""Photo tagging (agency M2): a vision model describes each library photo once, so the designer can pick by what is
in it (room, view, food, light, season) and never posts a photo of people without the owner's OK.

  * Model: brand_config.marketing_studio.vision_model (owner, audited), from adapters/vision (default Gemini Flash).
  * The photo is shrunk to at most 1024 px before it leaves HAIP; only active library photos are sent.
  * Result: media_assets.tags (schemas.marketing.PhotoTags), tag_model, tagged_at. An empty alt text is filled from
    the model's description. A photo with people gets people_ok = False until the owner confirms consent.
  * Celery `marketing_studio.tag_photo` after each upload; `POST /marketing/studio/media/tag-all` for the backlog.
"""
import io
from datetime import datetime, timezone
from typing import Optional

import structlog
from PIL import Image, ImageOps
from pydantic import ValidationError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.adapters import vision as vision_adapter
from app.core.audit import append_audit
from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.schemas.marketing import PHOTO_SUBJECTS, PhotoTags
from app.services import media_library_service as library
from app.services import usage_service
from app.services.marketing_content_service import MarketingError

log = structlog.get_logger()

SETTINGS_KEY = "marketing_studio"
MAX_SIDE = 1024
BACKLOG_BATCH = 50
PROMPT = (
    "You are tagging a hospitality business's own photo so the right photo can be chosen for social posts. "
    "Answer with ONE JSON object and nothing else, with these keys:\n"
    f"subjects: up to 6 of {list(PHOTO_SUBJECTS)} (what the photo mainly shows);\n"
    'light: one of "day", "golden_hour", "night", "indoor", "unknown";\n'
    'season: one of "monsoon", "winter", "summer", "any" (only if obvious from greenery, rain, mist, etc.);\n'
    "people: true if any person is visible; text_or_logo: true if readable text or a logo is visible;\n"
    "quality: 1-5 for sharpness, light and composition as a social post;\n"
    "mood: up to 4 single words (e.g. calm, cosy, romantic, family, adventurous, luxurious);\n"
    "description: one plain sentence under 30 words describing what is shown, with no names and no guesses about place."
)


def vision_model_key(tenant: Optional[Tenant]) -> str:
    cfg = ((tenant.brand_config or {}).get(SETTINGS_KEY) or {}) if tenant is not None else {}
    key = cfg.get("vision_model") if isinstance(cfg, dict) else None
    return key if key in vision_adapter.MODELS else vision_adapter.DEFAULT_MODEL


def set_vision_model(db: Session, tenant: Tenant, key: str, actor_id: str) -> str:
    try:
        vision_adapter.get_model(key)
    except vision_adapter.VisionModelBlocked as exc:
        raise MarketingError(422, "vision_model_unavailable", str(exc))
    before = vision_model_key(tenant)
    cfg = dict(tenant.brand_config or {})
    section = dict(cfg.get(SETTINGS_KEY) or {})
    section["vision_model"] = key
    cfg[SETTINGS_KEY] = section
    tenant.brand_config = cfg
    flag_modified(tenant, "brand_config")
    append_audit(db, tenant_id=tenant.id, action="marketing.vision_model.updated", actor_user_id=actor_id,
                 target_type="tenant", target_id=tenant.id, payload={"before": before, "after": key})
    return key


def _shrink(raw: bytes) -> bytes:
    with Image.open(io.BytesIO(raw)) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
    return out.getvalue()


def tag_asset(db: Session, tenant: Tenant, asset_id: str, *, read_bytes=None, describe=None) -> MediaAsset:
    """Tag one active library photo. Raises vision_adapter.VisionError (check .transient) or MarketingError."""
    asset = db.query(MediaAsset).filter_by(id=asset_id, tenant_id=tenant.id, status="active").first()
    if asset is None:
        raise MarketingError(404, "not_found", "No such photo in this workspace's library.")
    if not (asset.mime_type or "").startswith("image/"):
        raise MarketingError(422, "not_a_photo", "Only photos are tagged; describe a clip in its alt text.")
    try:
        model = vision_adapter.get_model(vision_model_key(tenant))
    except vision_adapter.VisionModelBlocked as exc:
        raise MarketingError(409, "vision_model_unavailable", str(exc))
    raw = (read_bytes or library._read_object)(asset.storage_key)
    answer, prov = (describe or vision_adapter.describe)(model, _shrink(raw), PROMPT)
    try:
        tags = PhotoTags.model_validate({k: v for k, v in answer.items() if k in PhotoTags.model_fields})
    except ValidationError as exc:
        raise vision_adapter.VisionError(f"The model's tags did not fit the format: {exc.errors()[0]['msg']}",
                                         transient=False)
    data = tags.model_dump()
    if data["people"] and "people" not in data["subjects"]:
        data["subjects"] = [*data["subjects"][:5], "people"]
    asset.tags, asset.tag_model, asset.tagged_at = data, model.key, datetime.now(timezone.utc)
    if not (asset.alt_text or "").strip():
        asset.alt_text = data["description"]
    usage_service.record(db, tenant.id, module="marketing_studio", kind="vision", units=1, provider=model.provider,
                         ref_type="media_asset", ref_id=asset.id, meta={"model": model.key, **{
                             k: prov.get(k) for k in ("input_tokens", "output_tokens", "est_cost_usd", "secs")}})
    return asset


def untagged(db: Session, tenant_id: str, limit: int = BACKLOG_BATCH) -> list[str]:
    return [r[0] for r in db.query(MediaAsset.id).filter(MediaAsset.tenant_id == tenant_id, MediaAsset.status == "active",
                                                         MediaAsset.tagged_at.is_(None),
                                                         MediaAsset.mime_type.like("image/%"))   # clips are not tagged
            .order_by(MediaAsset.created_at.desc()).limit(limit)]


def queue(tenant_id: str, asset_ids: list[str]) -> int:
    """Queue tagging; never raises (an untagged photo is still usable, just picked by its description)."""
    try:
        from app.workers.tasks.marketing_studio import tag_photo
        for a in asset_ids:
            tag_photo.delay(tenant_id, a)
        return len(asset_ids)
    except Exception as exc:  # noqa: BLE001
        log.warning("marketing_tag_queue_failed", tenant_id=tenant_id, error=str(exc))
        return 0


def set_people_ok(db: Session, tenant_id: str, asset_id: str, ok: bool, actor_id: str) -> MediaAsset:
    """The owner confirms the people in this photo agreed to it being posted (or withdraws that)."""
    asset = db.query(MediaAsset).filter_by(id=asset_id, tenant_id=tenant_id).first()
    if asset is None or asset.status != "active":
        raise MarketingError(404, "not_found", "No such photo in this workspace's library.")
    asset.people_ok = bool(ok)
    append_audit(db, tenant_id=tenant_id, action="media.people_consent", actor_user_id=actor_id, target_type="media_asset",
                 target_id=asset.id, payload={"people_ok": bool(ok)})
    return asset


def words(asset: MediaAsset) -> str:
    """Tag text the photo picker matches against (subjects, mood, light, season, description)."""
    t = asset.tags or {}
    return " ".join([*(s.replace("_", " ") for s in t.get("subjects") or []), *(t.get("mood") or []),
                     t.get("light") or "", t.get("season") or "", t.get("description") or ""])


def needs_consent(asset: MediaAsset) -> bool:
    return bool((asset.tags or {}).get("people")) and not asset.people_ok
