"""IVR call routing endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_roles
from app.core.config import settings as app_settings
from app.core.database import get_db
from app.core.encryption import decrypt_credentials
from app.models.user import User, UserRole
from app.schemas.ivr import IVRAnalyticsOut, IVRConfigIn, IVRConfigOut, IVROptionOut
from app.services import ivr_service
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/ivr", tags=["ivr"])


def _config_to_out(config, webhook_url: Optional[str] = None) -> IVRConfigOut:
    """Map IVRConfig ORM → IVRConfigOut, decrypting non-secret SIP fields."""
    sip_data: dict = {}
    if config.sip_credentials_enc:
        blob = (
            bytes(config.sip_credentials_enc)
            if isinstance(config.sip_credentials_enc, memoryview)
            else config.sip_credentials_enc
        )
        sip_data = decrypt_credentials(blob)

    options = [
        IVROptionOut(
            id=o.id,
            ivr_config_id=o.ivr_config_id,
            digit=o.digit,
            label=o.label,
            spoken_text=o.spoken_text,
            route_number=o.route_number,
            department=o.department,
            created_at=o.created_at,
        )
        for o in (config.options or [])
    ]

    return IVRConfigOut(
        id=config.id,
        tenant_id=config.tenant_id,
        greeting_text=config.greeting_text,
        language=config.language,
        business_hours_enabled=config.business_hours_enabled,
        business_hours=config.business_hours,
        vobiz_username=sip_data.get("username", ""),
        vobiz_server=sip_data.get("server", ""),
        sip_number=sip_data.get("sip_number", ""),
        dograh_workflow_id=config.dograh_workflow_id,
        dograh_phone_number_id=config.dograh_phone_number_id,
        is_active=config.is_active,
        webhook_url=webhook_url,
        options=options,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


def _webhook_url(tenant_slug: str) -> str:
    base = app_settings.API_BASE_URL or "https://your-haip-server.com"
    return f"{base}/api/v1/webhooks/dograh/{tenant_slug}"


@router.put("/config", response_model=IVRConfigOut)
def upsert_ivr_config(
    body: IVRConfigIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER)),
):
    """
    Create or replace IVR configuration.
    Encrypts Vobiz SIP credentials, replaces menu options, pushes workflow to Dograh.
    Owner role required.
    """
    config = ivr_service.upsert_config(db, current_user.tenant_id, body)
    log.info("ivr_config_upserted", tenant_id=current_user.tenant_id)
    return _config_to_out(config, _webhook_url(current_user.tenant.slug))


@router.get("/config", response_model=IVRConfigOut)
def get_ivr_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current IVR configuration. SIP password is never returned."""
    config = ivr_service.get_config(db, current_user.tenant_id)
    if not config:
        raise HTTPException(status_code=404, detail="IVR config not found — set it up first")
    return _config_to_out(config, _webhook_url(current_user.tenant.slug))


@router.post("/config/preview")
def preview_ivr_greeting(
    body: IVRConfigIn,
    current_user: User = Depends(get_current_user),
):
    """
    Return the full greeting text the caller would hear, without saving.
    Useful for testing before committing.
    """
    menu_lines = [f"Press {o.digit} for {o.label}." for o in sorted(body.options, key=lambda x: x.digit)]
    full_text = f"{body.greeting_text} {' '.join(menu_lines)}"
    return {
        "language": body.language,
        "greeting_text": full_text,
        "options": [
            {"digit": o.digit, "label": o.label, "spoken_text": o.spoken_text}
            for o in sorted(body.options, key=lambda x: x.digit)
        ],
    }


@router.get("/analytics", response_model=IVRAnalyticsOut)
def get_ivr_analytics(
    days: int = 30,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """IVR routing stats: total calls, calls by digit, avg duration."""
    if days < 1 or days > 365:
        raise HTTPException(status_code=400, detail="days must be between 1 and 365")
    return ivr_service.get_analytics(db, current_user.tenant_id, days=days)
