from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel
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


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


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
