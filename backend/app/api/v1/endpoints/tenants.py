from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional, List
from pydantic import BaseModel, field_validator
from app.core.database import get_db
from app.api.v1.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.models.tenant import Tenant
from app.schemas.tenant import TenantOut, TenantUpdate
from app.schemas.user import UserOut

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
        merged.update(data.pop("brand_config"))
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
