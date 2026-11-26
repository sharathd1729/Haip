"""WhatsApp hours and welcome (services/wa_bot_settings.py): business hours + holidays, first-message welcome, location
reply, STOP / START confirmation text. Owner and manager read and change them; every change is audited."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.deps import require_roles
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.wa_bot import WaBotSettingsIn
from app.services import wa_bot_settings

router = APIRouter(tags=["whatsapp-bot-settings"])
_staff = require_roles(UserRole.OWNER, UserRole.MANAGER)


def _tenant(db: Session, user: User) -> Tenant:
    tenant = db.query(Tenant).filter_by(id=user.tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.get("/whatsapp/bot-settings")
def get_settings(current_user: User = Depends(_staff), db: Session = Depends(get_db)):
    return {**wa_bot_settings.view(_tenant(db, current_user)), "defaults": wa_bot_settings.DEFAULTS}


@router.put("/whatsapp/bot-settings")
def put_settings(body: WaBotSettingsIn, current_user: User = Depends(_staff), db: Session = Depends(get_db)):
    tenant = _tenant(db, current_user)
    changes = wa_bot_settings.update(db, tenant, current_user.id, body)
    db.commit()
    db.refresh(tenant)
    return {**wa_bot_settings.view(tenant), "defaults": wa_bot_settings.DEFAULTS, "changed": sorted(changes)}
