"""GET /security/status: what Settings › Security may claim, read from the running configuration (services/security_status)."""

from fastapi import APIRouter, Depends

from app.api.v1.deps import require_roles
from app.models.user import User, UserRole
from app.services import security_status

router = APIRouter(prefix="/security", tags=["security"])


@router.get("/status")
def get_security_status(current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER))):
    # Key NAMES and set / missing / not used only, never a value.
    return security_status.status(current_user)
