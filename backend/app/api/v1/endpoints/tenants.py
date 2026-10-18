from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel, field_validator
from app.core.database import get_db
from app.api.v1.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.models.tenant import Tenant
from app.schemas.tenant import TenantOut, TenantUpdate
from app.schemas.user import UserOut
import structlog

log = structlog.get_logger()
router = APIRouter(tags=["tenants"])


# ─── Branding schemas ─────────────────────────────────────────────────────────

class BrandingTheme(BaseModel):
    primaryColor: Optional[str] = None
    sidebarColor: Optional[str] = None
    logoUrl: Optional[str] = None
    logoDarkUrl: Optional[str] = None
    fontFamily: Optional[str] = None
    radiusScale: Optional[str] = None   # "sharp" | "rounded" | "pill"
    companyName: Optional[str] = None
    tagline: Optional[str] = None


@router.get("/me")
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = UserOut.model_validate(current_user).model_dump()
    # Expose onboarding_step so the frontend session JWT can track it correctly
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    data["onboarding_step"] = int((tenant.brand_config or {}).get("onboarding_step", 0)) if tenant else 0
    return data


@router.get("/tenants/me", response_model=TenantOut)
def get_my_tenant(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.patch("/tenants/me", response_model=TenantOut)
def update_my_tenant(
    body: TenantUpdate,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    data = body.model_dump(exclude_none=True)

    # Deep-merge brand_config instead of replacing
    if "brand_config" in data:
        merged = dict(tenant.brand_config or {})
        incoming = data.pop("brand_config")
        if "lead_autopilot" in incoming:
            # Owner-only and audited: PUT /lead-autopilot/settings. A manager must not switch it on through here.
            raise HTTPException(status_code=422, detail="Change lead autopilot settings in Settings > Lead autopilot")
        if "price_disclosure" in incoming:
            from app.services.price_policy import PRICE_MODES
            if incoming["price_disclosure"] not in PRICE_MODES:
                raise HTTPException(status_code=422, detail=f"price_disclosure must be one of {', '.join(PRICE_MODES)}")
        merged.update(incoming)
        tenant.brand_config = merged

    # `config` dict is merged into brand_config (used for onboarding_step etc.)
    if "config" in data:
        merged = dict(tenant.brand_config or {})
        merged.update(data.pop("config"))
        tenant.brand_config = merged

    for field, value in data.items():
        setattr(tenant, field, value)

    db.commit()
    db.refresh(tenant)
    return tenant


# ─── Branding endpoints ───────────────────────────────────────────────────────

_BRANDING_KEY = "branding_theme"


# ─── AI Concierge mode ───────────────────────────────────────────────────────
# Settings > AI Concierge was a mock: the Save button set a local "saved!"
# flag and made no request, and the form initialised from a hardcoded
# useState("shadow") rather than the server. Choosing Autonomous appeared to
# work and silently reverted on the next mount. These endpoints are what it
# should have been calling.

class AIModeSettings(BaseModel):
    wa_ai_mode_default: Optional[str] = None
    wa_ai_confidence_threshold: Optional[float] = None
    ig_ai_mode_default: Optional[str] = None
    ig_ai_confidence_threshold: Optional[float] = None

    @field_validator("wa_ai_mode_default", "ig_ai_mode_default")
    @classmethod
    def _valid_mode(cls, v):
        if v is not None and v not in ("off", "shadow", "autonomous"):
            raise ValueError("mode must be one of: off, shadow, autonomous")
        return v

    @field_validator("wa_ai_confidence_threshold", "ig_ai_confidence_threshold")
    @classmethod
    def _valid_threshold(cls, v):
        if v is not None and not (0.5 <= v <= 1.0):
            raise ValueError("confidence threshold must be between 0.5 and 1.0")
        return v


@router.get("/tenants/me/ai-mode", response_model=AIModeSettings)
def get_ai_mode(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return AIModeSettings(
        wa_ai_mode_default=tenant.wa_ai_mode_default,
        wa_ai_confidence_threshold=tenant.wa_ai_confidence_threshold,
        ig_ai_mode_default=tenant.ig_ai_mode_default,
        ig_ai_confidence_threshold=tenant.ig_ai_confidence_threshold,
    )


@router.patch("/tenants/me/ai-mode", response_model=AIModeSettings)
def update_ai_mode(
    body: AIModeSettings,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Set the AI concierge mode per channel.

    Takes effect on the next inbound message for every conversation on that
    channel, not just new ones -- concierge_draft resolves the mode through
    ai_mode_service at draft time.
    """
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    import structlog
    _log = structlog.get_logger()

    changed = {}
    for field in ("wa_ai_mode_default", "wa_ai_confidence_threshold",
                  "ig_ai_mode_default", "ig_ai_confidence_threshold"):
        val = getattr(body, field)
        if val is not None and getattr(tenant, field) != val:
            changed[field] = {"from": getattr(tenant, field), "to": val}
            setattr(tenant, field, val)

    db.commit()
    db.refresh(tenant)

    if changed:
        # Turning autonomy on means unreviewed messages start reaching real
        # guests -- that transition needs to be attributable after the fact.
        _log.info(
            "ai_mode_changed",
            tenant_id=tenant.id, actor_user_id=current_user.id, changes=changed,
        )

    return AIModeSettings(
        wa_ai_mode_default=tenant.wa_ai_mode_default,
        wa_ai_confidence_threshold=tenant.wa_ai_confidence_threshold,
        ig_ai_mode_default=tenant.ig_ai_mode_default,
        ig_ai_confidence_threshold=tenant.ig_ai_confidence_threshold,
    )


# ─── AI safety controls (kill switch + escalation keywords) ──────────────────

class KillSwitchRequest(BaseModel):
    enabled: bool
    reason: Optional[str] = None


class AIRateLimits(BaseModel):
    ai_max_sends_per_conversation_hour: Optional[int] = None
    ai_max_consecutive_replies: Optional[int] = None
    ai_max_sends_per_tenant_hour: Optional[int] = None

    @field_validator(
        "ai_max_sends_per_conversation_hour",
        "ai_max_consecutive_replies",
        "ai_max_sends_per_tenant_hour",
    )
    @classmethod
    def _sane_limit(cls, v):
        # 0 would disable autonomous sending by the back door; that is what
        # the kill switch is for, and it should be visible as such.
        if v is not None and not (1 <= v <= 1000):
            raise ValueError("limit must be between 1 and 1000")
        return v


class AISafetyOut(BaseModel):
    ai_kill_switch: bool
    ai_kill_switch_at: Optional[str] = None
    ai_kill_switch_by: Optional[str] = None
    ai_kill_switch_reason: Optional[str] = None
    ai_escalation_keywords: list[str] = []
    default_escalation_categories: dict = {}
    ai_max_sends_per_conversation_hour: int = 6
    ai_max_consecutive_replies: int = 3
    ai_max_sends_per_tenant_hour: int = 60


def _safety_out(tenant) -> "AISafetyOut":
    from app.services.escalation_policy import DEFAULT_ESCALATION_KEYWORDS
    return AISafetyOut(
        ai_kill_switch=bool(tenant.ai_kill_switch),
        ai_kill_switch_at=tenant.ai_kill_switch_at.isoformat() if tenant.ai_kill_switch_at else None,
        ai_kill_switch_by=tenant.ai_kill_switch_by,
        ai_kill_switch_reason=tenant.ai_kill_switch_reason,
        ai_escalation_keywords=list(tenant.ai_escalation_keywords or []),
        default_escalation_categories={k: list(v) for k, v in DEFAULT_ESCALATION_KEYWORDS.items()},
        ai_max_sends_per_conversation_hour=tenant.ai_max_sends_per_conversation_hour or 6,
        ai_max_consecutive_replies=tenant.ai_max_consecutive_replies or 3,
        ai_max_sends_per_tenant_hour=tenant.ai_max_sends_per_tenant_hour or 60,
    )


@router.get("/tenants/me/ai-safety", response_model=AISafetyOut)
def get_ai_safety(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return _safety_out(tenant)


@router.post("/tenants/me/ai-kill-switch", response_model=AISafetyOut)
def set_kill_switch(
    body: KillSwitchRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Emergency stop. When enabled the AI stops sending to guests on every
    channel immediately; drafting continues so agents keep the assist."""
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    from datetime import datetime, timezone as _tz
    import structlog
    _log = structlog.get_logger()

    tenant.ai_kill_switch = bool(body.enabled)
    tenant.ai_kill_switch_at = datetime.now(_tz.utc) if body.enabled else None
    tenant.ai_kill_switch_by = current_user.id if body.enabled else None
    tenant.ai_kill_switch_reason = (body.reason or None) if body.enabled else None
    db.commit()
    db.refresh(tenant)

    # Both directions are audit-worthy: switching it back off is the moment
    # unreviewed messages can start reaching guests again.
    _log.warning(
        "ai_kill_switch_changed",
        tenant_id=tenant.id, actor_user_id=current_user.id,
        enabled=bool(body.enabled), reason=body.reason,
    )
    return _safety_out(tenant)


@router.patch("/tenants/me/ai-rate-limits", response_model=AISafetyOut)
def set_ai_rate_limits(
    body: AIRateLimits,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Tune the caps on autonomous sending."""
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    for field in ("ai_max_sends_per_conversation_hour", "ai_max_consecutive_replies",
                  "ai_max_sends_per_tenant_hour"):
        val = getattr(body, field)
        if val is not None:
            setattr(tenant, field, val)
    db.commit()
    db.refresh(tenant)
    return _safety_out(tenant)


@router.put("/tenants/me/ai-escalation-keywords", response_model=AISafetyOut)
def set_escalation_keywords(
    body: dict,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Replace the tenant's *additional* escalation keywords.

    These add to the built-in list (refunds, legal, safety, ...) -- they
    never replace it, so a tenant cannot accidentally disable the defaults
    by clearing this field.
    """
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    raw = (body or {}).get("keywords", [])
    if not isinstance(raw, list):
        raise HTTPException(status_code=422, detail="keywords must be a list of strings")

    cleaned, seen = [], set()
    for k in raw:
        s = str(k or "").strip().lower()
        # A 1-2 char keyword would match constantly; reject rather than
        # silently accept a rule that escalates every message.
        if len(s) < 3 or s in seen:
            continue
        seen.add(s)
        cleaned.append(s)
    if len(cleaned) > 100:
        raise HTTPException(status_code=422, detail="At most 100 custom keywords")

    tenant.ai_escalation_keywords = cleaned
    db.commit()
    db.refresh(tenant)
    return _safety_out(tenant)


@router.get("/tenants/me/branding", response_model=BrandingTheme)
def get_branding(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the tenant's saved brand theme (or empty dict if not set yet)."""
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    cfg = tenant.brand_config or {}
    stored = cfg.get(_BRANDING_KEY, {})
    return BrandingTheme(**stored)


@router.patch("/tenants/me/branding", response_model=BrandingTheme)
def update_branding(
    body: BrandingTheme,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Persist brand theme. Deep-merged into brand_config[branding_theme]."""
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    cfg = dict(tenant.brand_config or {})
    existing = dict(cfg.get(_BRANDING_KEY, {}))

    # Merge: only overwrite fields that were explicitly sent (non-None)
    patch = body.model_dump(exclude_none=True)
    existing.update(patch)
    cfg[_BRANDING_KEY] = existing
    tenant.brand_config = cfg

    db.commit()
    db.refresh(tenant)
    return BrandingTheme(**cfg[_BRANDING_KEY])


# ─── Pipeline config endpoints ────────────────────────────────────────────────

_VALID_STAGE_KEYS = {
    "unqualified", "general_enquiry", "rnr", "active", "unsuitable",
    "lost", "sold", "collaboration_engagement",
}

# Leads360 default taxonomy (migration 049/062 / pipeline_stage_service.
# seed_default_pipeline_stages) -- this legacy /tenants/me/pipeline-config
# fallback is kept in sync for tenants that somehow have no pipeline_stages
# rows at all, even though the leads board itself reads /pipeline-stages.
DEFAULT_PIPELINE_STAGES = [
    {"key": "unqualified",              "label": "Unqualified",              "color": "#94a3b8", "visible": True, "order": 0},
    {"key": "general_enquiry",          "label": "General Enquiry",          "color": "#6b7280", "visible": True, "order": 1},
    {"key": "rnr",                      "label": "RNR",                      "color": "#f59e0b", "visible": True, "order": 2},
    {"key": "active",                   "label": "Active",                   "color": "#6366f1", "visible": True, "order": 3},
    {"key": "unsuitable",               "label": "Unsuitable",               "color": "#8b5cf6", "visible": True, "order": 4},
    {"key": "lost",                     "label": "Lost",                     "color": "#ef4444", "visible": True, "order": 5},
    {"key": "sold",                     "label": "Sold",                     "color": "#22c55e", "visible": True, "order": 6},
    {"key": "collaboration_engagement", "label": "Collaboration Engagement", "color": "#06b6d4", "visible": True, "order": 7},
]


class PipelineStage(BaseModel):
    key: str
    label: str
    color: str
    visible: bool
    order: int

    @field_validator("key")
    @classmethod
    def key_must_be_valid(cls, v: str) -> str:
        if v not in _VALID_STAGE_KEYS:
            raise ValueError(f"Invalid stage key: {v}")
        return v

    @field_validator("label")
    @classmethod
    def label_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Stage label cannot be empty")
        if len(v) > 40:
            raise ValueError("Stage label max 40 chars")
        return v


class PipelineConfigBody(BaseModel):
    stages: List[PipelineStage]

    @field_validator("stages")
    @classmethod
    def validate_stages(cls, v: list) -> list:
        if len(v) < 2:
            raise ValueError("Need at least 2 stages")
        if len(v) > 10:
            raise ValueError("Max 10 stages")
        orders = [s.order for s in v]
        if len(set(orders)) != len(orders):
            raise ValueError("Stage order values must be unique")
        visible_count = sum(1 for s in v if s.visible)
        if visible_count < 2:
            raise ValueError("At least 2 stages must be visible")
        return v


class PipelineConfigOut(BaseModel):
    stages: list


@router.get("/tenants/me/pipeline-config", response_model=PipelineConfigOut)
def get_pipeline_config(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    stages = (tenant.pipeline_config or {}).get("stages") or DEFAULT_PIPELINE_STAGES
    return {"stages": stages}


@router.put("/tenants/me/pipeline-config", response_model=PipelineConfigOut)
def update_pipeline_config(
    body: PipelineConfigBody,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    stages = [s.model_dump() for s in body.stages]
    tenant.pipeline_config = {"stages": stages}
    db.commit()
    return {"stages": stages}


# ─── IVR call routing (migration 084) ─────────────────────────────────────────
# webhooks_vobiz.py dials whatever these settings resolve to via
# ivr_routing_service -- "single" (default) keeps today's behaviour of one
# fixed forward_number until a tenant opts users into the routing pool.

_ALLOWED_GREETING_TYPES = {
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/mp4", "audio/m4a",
    # Browsers report a .mp4 file's type from its extension, not its actual
    # contents -- almost always "video/mp4" even for an audio-only recording
    # (the same container MPEG-4 audio and M4A both use). Confirmed live:
    # a voice-recorder-app export named .mp4 was rejected outright.
    "video/mp4",
}
_ALLOWED_GREETING_EXTS = {".mp3", ".wav", ".m4a", ".mp4"}
_MAX_GREETING_MB = 10


class IVRRoutingSettings(BaseModel):
    ivr_routing_strategy: Optional[str] = None
    has_greeting_audio: bool = False
    has_voicemail_audio: bool = False
    eligible_agents: List[dict] = []

    @field_validator("ivr_routing_strategy")
    @classmethod
    def _valid_strategy(cls, v):
        from app.services.ivr_routing_service import VALID_STRATEGIES
        if v is not None and v not in VALID_STRATEGIES:
            raise ValueError(f"strategy must be one of: {', '.join(VALID_STRATEGIES)}")
        return v


@router.get("/tenants/me/ivr-routing", response_model=IVRRoutingSettings)
def get_ivr_routing(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    from app.services.ivr_routing_service import get_eligible_agents_summary
    return IVRRoutingSettings(
        ivr_routing_strategy=tenant.ivr_routing_strategy,
        has_greeting_audio=bool(tenant.ivr_greeting_audio_key),
        has_voicemail_audio=bool(tenant.ivr_voicemail_audio_key),
        eligible_agents=get_eligible_agents_summary(db, tenant.id),
    )


@router.get("/tenants/me/ivr-greeting-audio/url")
def get_ivr_greeting_audio_url(
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Short-lived playback URL for the currently-configured greeting, so
    an admin can actually hear what a Generate/Upload produced instead of
    only seeing a "Configured" checkmark -- confirmed live this was the
    real gap: TTS generation was working every time, there was just no
    way to tell from the UI."""
    from app.services import media_storage

    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant or not tenant.ivr_greeting_audio_key:
        raise HTTPException(status_code=404, detail="No greeting configured yet.")
    url = media_storage.get_presigned_media_url(tenant.ivr_greeting_audio_key, expires_in=300)
    if not url:
        raise HTTPException(status_code=502, detail="Could not generate a playback link. Try again.")
    return {"url": url}


@router.patch("/tenants/me/ivr-routing", response_model=IVRRoutingSettings)
def update_ivr_routing(
    body: IVRRoutingSettings,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if body.ivr_routing_strategy is not None:
        tenant.ivr_routing_strategy = body.ivr_routing_strategy
        db.commit()
    from app.services.ivr_routing_service import get_eligible_agents_summary
    return IVRRoutingSettings(
        ivr_routing_strategy=tenant.ivr_routing_strategy,
        has_greeting_audio=bool(tenant.ivr_greeting_audio_key),
        has_voicemail_audio=bool(tenant.ivr_voicemail_audio_key),
        eligible_agents=get_eligible_agents_summary(db, tenant.id),
    )


@router.post("/tenants/me/ivr-greeting-audio", response_model=IVRRoutingSettings)
async def upload_ivr_greeting_audio(
    file: UploadFile = File(...),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Client-uploaded greeting played before the agent leg dials (see
    webhooks_vobiz.py). One per tenant -- a re-upload overwrites the old
    file, same key, so nothing needs separate cleanup."""
    from pathlib import Path
    from app.services import media_storage

    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    content_type = (file.content_type or "").lower()
    ext = Path(file.filename or "greeting.mp3").suffix.lower() or ".mp3"
    if content_type not in _ALLOWED_GREETING_TYPES and ext not in _ALLOWED_GREETING_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported audio format '{ext}'. Use MP3, WAV, or M4A.")

    audio_bytes = await file.read()
    size_mb = len(audio_bytes) / (1024 * 1024)
    if size_mb > _MAX_GREETING_MB:
        raise HTTPException(status_code=400, detail=f"File too large ({size_mb:.1f} MB). Max {_MAX_GREETING_MB} MB.")

    key = media_storage.upload_ivr_greeting(
        tenant.id, audio_bytes, content_type or "audio/mpeg", ext.lstrip("."),
    )
    tenant.ivr_greeting_audio_key = key
    db.commit()

    log.info("ivr_greeting_uploaded", tenant_id=tenant.id, actor_user_id=current_user.id)
    from app.services.ivr_routing_service import get_eligible_agents_summary
    return IVRRoutingSettings(
        ivr_routing_strategy=tenant.ivr_routing_strategy,
        has_greeting_audio=True,
        has_voicemail_audio=bool(tenant.ivr_voicemail_audio_key),
        eligible_agents=get_eligible_agents_summary(db, tenant.id),
    )


# Sarvam's per-request text cap is well above this; 2000 chars is ~4 minutes
# of speech, far more than any sane IVR greeting.
_MAX_GREETING_TEXT_CHARS = 2000


class IVRGreetingTTSRequest(BaseModel):
    text: str
    speaker: str = "anushka"


@router.post("/tenants/me/ivr-greeting-tts", response_model=IVRRoutingSettings)
def generate_ivr_greeting_tts(
    body: IVRGreetingTTSRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Generate the greeting from text via Sarvam TTS and set it as this
    tenant's IVR greeting -- same S3 key and same downstream playback path
    (webhooks_vobiz.py) as a manual upload, so this is just a second way to
    produce the same artifact.

    Synchronous on purpose: a ~50-word TTS render is a bounded 1-3s call,
    much closer to the sibling upload endpoint's inline S3 write than to an
    LLM completion (which CLAUDE.md rightly pushes to Celery). Keeping it
    inline means the admin gets immediate pass/fail on a one-off setup
    action, with no polling UI to build."""
    from app.services import media_storage, tts_service

    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Greeting text is required.")
    if len(text) > _MAX_GREETING_TEXT_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Greeting text too long ({len(text)} chars). Max {_MAX_GREETING_TEXT_CHARS}.",
        )

    try:
        audio_bytes = tts_service.generate_speech(text, speaker=body.speaker)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Voice generation failed: {exc}")

    key = media_storage.upload_ivr_greeting(tenant.id, audio_bytes, "audio/mpeg", "mp3")
    tenant.ivr_greeting_audio_key = key
    db.commit()

    log.info(
        "ivr_greeting_tts_generated",
        tenant_id=tenant.id, actor_user_id=current_user.id, speaker=body.speaker,
    )
    from app.services.ivr_routing_service import get_eligible_agents_summary
    return IVRRoutingSettings(
        ivr_routing_strategy=tenant.ivr_routing_strategy,
        has_greeting_audio=True,
        has_voicemail_audio=bool(tenant.ivr_voicemail_audio_key),
        eligible_agents=get_eligible_agents_summary(db, tenant.id),
    )


# ── Voicemail slot -- plays instead of dialing agents (no-answer fallback,
# or outright skipped straight to when outside business hours; see
# webhooks_vobiz.py). Mirrors the greeting-slot endpoints above exactly. ──

@router.get("/tenants/me/ivr-voicemail-audio/url")
def get_ivr_voicemail_audio_url(
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    from app.services import media_storage

    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant or not tenant.ivr_voicemail_audio_key:
        raise HTTPException(status_code=404, detail="No voicemail message configured yet.")
    url = media_storage.get_presigned_media_url(tenant.ivr_voicemail_audio_key, expires_in=300)
    if not url:
        raise HTTPException(status_code=502, detail="Could not generate a playback link. Try again.")
    return {"url": url}


@router.post("/tenants/me/ivr-voicemail-audio", response_model=IVRRoutingSettings)
async def upload_ivr_voicemail_audio(
    file: UploadFile = File(...),
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Client-uploaded voicemail prompt -- same validation/storage as the
    greeting upload, different tenant column and S3 kind."""
    from pathlib import Path
    from app.services import media_storage

    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    content_type = (file.content_type or "").lower()
    ext = Path(file.filename or "voicemail.mp3").suffix.lower() or ".mp3"
    if content_type not in _ALLOWED_GREETING_TYPES and ext not in _ALLOWED_GREETING_EXTS:
        raise HTTPException(status_code=400, detail=f"Unsupported audio format '{ext}'. Use MP3, WAV, or M4A.")

    audio_bytes = await file.read()
    size_mb = len(audio_bytes) / (1024 * 1024)
    if size_mb > _MAX_GREETING_MB:
        raise HTTPException(status_code=400, detail=f"File too large ({size_mb:.1f} MB). Max {_MAX_GREETING_MB} MB.")

    key = media_storage.upload_ivr_greeting(
        tenant.id, audio_bytes, content_type or "audio/mpeg", ext.lstrip("."), kind="voicemail",
    )
    tenant.ivr_voicemail_audio_key = key
    db.commit()

    log.info("ivr_voicemail_uploaded", tenant_id=tenant.id, actor_user_id=current_user.id)
    from app.services.ivr_routing_service import get_eligible_agents_summary
    return IVRRoutingSettings(
        ivr_routing_strategy=tenant.ivr_routing_strategy,
        has_greeting_audio=bool(tenant.ivr_greeting_audio_key),
        has_voicemail_audio=True,
        eligible_agents=get_eligible_agents_summary(db, tenant.id),
    )


class IVRVoicemailTTSRequest(BaseModel):
    text: str
    speaker: str = "anushka"


@router.post("/tenants/me/ivr-voicemail-tts", response_model=IVRRoutingSettings)
def generate_ivr_voicemail_tts(
    body: IVRVoicemailTTSRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Sarvam-generated voicemail prompt -- identical shape to
    generate_ivr_greeting_tts, writes to the voicemail slot instead."""
    from app.services import media_storage, tts_service

    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Voicemail text is required.")
    if len(text) > _MAX_GREETING_TEXT_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Voicemail text too long ({len(text)} chars). Max {_MAX_GREETING_TEXT_CHARS}.",
        )

    try:
        audio_bytes = tts_service.generate_speech(text, speaker=body.speaker)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Voice generation failed: {exc}")

    key = media_storage.upload_ivr_greeting(tenant.id, audio_bytes, "audio/mpeg", "mp3", kind="voicemail")
    tenant.ivr_voicemail_audio_key = key
    db.commit()

    log.info(
        "ivr_voicemail_tts_generated",
        tenant_id=tenant.id, actor_user_id=current_user.id, speaker=body.speaker,
    )
    from app.services.ivr_routing_service import get_eligible_agents_summary
    return IVRRoutingSettings(
        ivr_routing_strategy=tenant.ivr_routing_strategy,
        has_greeting_audio=bool(tenant.ivr_greeting_audio_key),
        has_voicemail_audio=True,
        eligible_agents=get_eligible_agents_summary(db, tenant.id),
    )


# ── Lead assignment rules ────────────────────────────────────────────────────
# How new leads get an owner (round robin / balanced / first to act, plus
# returning-guest, call-answerer, reassign-if-not-contacted and working-hours
# rules). See app/services/lead_assignment_service.py.
from app.schemas.lead_assignment import LeadAssignmentUpdate  # noqa: E402

def _lead_assignment_out(db: Session, tenant: Tenant):
    from app.schemas.lead_assignment import AssignableAgent, LeadAssignmentSettings
    from app.services import lead_assignment_service as svc

    cfg = svc.get_config(tenant)
    team = svc.assignable_team(db, tenant.id)
    counts = svc.open_uncontacted_counts(db, tenant.id, [u.id for u in team])
    return LeadAssignmentSettings(
        **cfg.model_dump(),
        agents=[
            AssignableAgent(
                id=u.id, name=u.name, role=u.role.value,
                takes_leads=bool(u.is_available_for_assignment),
                open_uncontacted=counts.get(u.id, 0),
            )
            for u in team
        ],
        unassigned_open=svc.unassigned_open_count(db, tenant.id),
    )


@router.get("/tenants/me/lead-assignment")
def get_lead_assignment(
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return _lead_assignment_out(db, tenant)


@router.patch("/tenants/me/lead-assignment")
def update_lead_assignment(
    body: LeadAssignmentUpdate,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    """Save the method + rules and which team members take new leads."""
    from app.core.audit import append_audit
    from app.services import lead_assignment_service as svc

    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    changes: dict = {}
    if body.config is not None:
        tenant.lead_assignment_config = body.config.model_dump()
        changes["config"] = tenant.lead_assignment_config
    if body.agents:
        team = {u.id: u for u in svc.assignable_team(db, tenant.id)}
        unknown = [uid for uid in body.agents if uid not in team]
        if unknown:
            raise HTTPException(status_code=422, detail="Some of those people aren't on this team.")
        for uid, takes in body.agents.items():
            team[uid].is_available_for_assignment = bool(takes)
        changes["agents"] = body.agents

    if changes:
        append_audit(
            db, tenant_id=tenant.id, action="lead_assignment.updated",
            actor_user_id=current_user.id, target_type="tenant", target_id=tenant.id, payload=changes,
        )
        db.commit()
        db.refresh(tenant)
        log.info("lead_assignment_updated", tenant_id=tenant.id, actor_user_id=current_user.id)
    return _lead_assignment_out(db, tenant)

