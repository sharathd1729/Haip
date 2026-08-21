"""Agent worklist — the "who needs contacting right now" feed.

GET /worklist

Deliberately not behind require_module("analytics"): this is an inbox-style
operational view, not reporting. Gating it on the analytics module would
hide an agent's own follow-ups from them whenever that module is off (it is
currently off for some tenants), which is the opposite of the intent.
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.core.database import get_db
from app.models.user import User, UserRole
from app.services import worklist_service

log = structlog.get_logger()

router = APIRouter(prefix="/worklist", tags=["worklist"])


@router.get("")
def get_worklist(
    hours: int = Query(default=24, ge=1, le=168),
    mine_only: Optional[bool] = Query(
        default=None,
        description="Agents are always scoped to themselves; owners/managers default to tenant-wide.",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    is_owner_view = current_user.role in (UserRole.OWNER, UserRole.MANAGER)

    # An agent always sees only their own assignments, whatever they pass --
    # same rule the dashboard applies. Owners and managers see everything by
    # default and can narrow to themselves.
    if is_owner_view:
        scope_user_id = current_user.id if mine_only else None
    else:
        scope_user_id = current_user.id

    data = worklist_service.build_worklist(
        db, current_user.tenant_id, scope_user_id=scope_user_id, hours=hours,
    )
    data["scope"] = "mine" if scope_user_id else "team"
    return data
