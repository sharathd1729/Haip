"""Settings > AI (docs/ai/AI_SWITCHES_SPEC.md step 2): every AI switch of the workspace with its last-30-day cost.

GET  /settings/ai: reply modes, feature switches, cost and uses per row (usage_events), drafts nobody used
     (ai_draft_outcomes "expired").
PATCH /settings/ai: change switches; one audit row `ai.feature_changed` (old -> new) per change.
Owner and manager only (costs are business data). The gate re-reads switches within a minute; PATCH clears its cache.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.v1.deps import require_roles
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.ai_settings import AISettingsUpdate
from app.services import ai_features

router = APIRouter(prefix="/settings/ai", tags=["settings"])

_owner_or_manager = require_roles(UserRole.OWNER, UserRole.MANAGER)


def _tenant(db: Session, user: User) -> Tenant:
    tenant = db.query(Tenant).filter_by(id=user.tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return tenant


@router.get("")
def get_ai_settings(current_user: User = Depends(_owner_or_manager), db: Session = Depends(get_db)) -> dict:
    return ai_features.view(db, _tenant(db, current_user))


@router.patch("")
def update_ai_settings(
    body: AISettingsUpdate,
    current_user: User = Depends(_owner_or_manager),
    db: Session = Depends(get_db),
) -> dict:
    tenant = _tenant(db, current_user)
    changes = ai_features.apply(db, tenant, current_user.id, body.features, body.reply_modes, body.thresholds)
    db.commit()
    if changes:
        ai_features.forget(tenant.id)
    db.refresh(tenant)
    return {**ai_features.view(db, tenant), "changed": changes}
