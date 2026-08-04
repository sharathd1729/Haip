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
