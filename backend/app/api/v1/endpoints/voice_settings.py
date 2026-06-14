"""Voice platform settings endpoint."""
import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_roles
from app.core.config import settings as app_settings
from app.core.database import get_db
from app.core.encryption import encrypt_credentials, decrypt_credentials
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.dograh import VoicePlatformOut, VoicePlatformUpdateRequest
import structlog

log = structlog.get_logger()
router = APIRouter(tags=["voice-settings"])


@router.put("/settings/voice-platform", response_model=VoicePlatformOut)
def update_voice_platform(
    body: VoicePlatformUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.OWNER)),
):
    """
    Configure the tenant's active voice platform.
    Auth: owner role only.
    Generates per-tenant Dograh webhook secret if not already set.
    """
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Update voice platform fields
    tenant.voice_platform = body.voice_platform
    if body.dograh_agent_id is not None:
        tenant.dograh_agent_id = body.dograh_agent_id
    if body.sip_trunk_provider is not None:
        tenant.sip_trunk_provider = body.sip_trunk_provider
    if body.sip_trunk_number is not None:
        tenant.sip_trunk_number = body.sip_trunk_number

    # For Dograh: generate per-tenant webhook secret if not already set
    webhook_url = None
    if body.voice_platform == "dograh":
        existing_secret = ""
        if tenant.dograh_webhook_secret_enc:
            creds = decrypt_credentials(tenant.dograh_webhook_secret_enc)
            existing_secret = creds.get("webhook_secret", "")

        if not existing_secret:
            new_secret = secrets.token_hex(32)
            tenant.dograh_webhook_secret_enc = encrypt_credentials({"webhook_secret": new_secret})
            log.info("dograh_webhook_secret_generated", tenant_id=tenant.id)

        base_url = app_settings.API_BASE_URL or "https://your-haip-server.com"
        webhook_url = f"{base_url}/api/v1/webhooks/dograh/{tenant.slug}"

    db.commit()

    log.info(
        "voice_platform_updated",
        tenant_id=tenant.id,
        voice_platform=body.voice_platform,
    )

    return VoicePlatformOut(
        voice_platform=tenant.voice_platform or "callerdesk",
        dograh_agent_id=tenant.dograh_agent_id,
        sip_trunk_provider=tenant.sip_trunk_provider,
        sip_trunk_number=tenant.sip_trunk_number,
        webhook_url=webhook_url,
    )


@router.get("/settings/voice-platform", response_model=VoicePlatformOut)
def get_voice_platform(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current voice platform configuration for this tenant."""
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    webhook_url = None
    voice_platform = tenant.voice_platform or "callerdesk"
    if voice_platform == "dograh":
        base_url = app_settings.API_BASE_URL or "https://your-haip-server.com"
        webhook_url = f"{base_url}/api/v1/webhooks/dograh/{tenant.slug}"

    return VoicePlatformOut(
        voice_platform=voice_platform,
        dograh_agent_id=tenant.dograh_agent_id,
        sip_trunk_provider=tenant.sip_trunk_provider,
        sip_trunk_number=tenant.sip_trunk_number,
        webhook_url=webhook_url,
    )
