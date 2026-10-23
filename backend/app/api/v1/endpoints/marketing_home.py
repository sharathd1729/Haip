"""Marketing Studio Home (plan 24 Oct 2026, phase 0). Module `marketing_studio`.

GET /marketing/studio/setup     the setup checklist: each item done / not done with one fix (marketing.read)
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User
from app.services import marketing_setup
from app.services.authz_service import require_capability

router = APIRouter(prefix="/marketing/studio", tags=["marketing-studio"])

_module = Depends(require_module("marketing_studio"))
_read = Depends(require_capability("marketing.read"))


def _tenant(db: Session, user: User) -> Tenant:
    return db.query(Tenant).filter_by(id=user.tenant_id).one()


@router.get("/setup")
def setup(user: User = Depends(get_current_user), db: Session = Depends(get_db), _m=_module, _c=_read):
    return marketing_setup.checklist(db, _tenant(db, user))
