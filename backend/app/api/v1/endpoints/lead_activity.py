"""Detailed per-lead report — in-app Lead Activity page.

Same data (and the same lead_activity_service query) that feeds the daily
agent/owner email reports' Lead breakdown sections -- this is the "View
all N leads" destination linked from the owner email's condensed
per-agent rows.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.v1.deps import get_current_user
from app.core.database import get_db
from app.models.user import User, UserRole
from app.services import lead_activity_service
from sqlalchemy.orm import Session

router = APIRouter(prefix="/leads-activity", tags=["leads-activity"])


@router.get("")
def get_leads_activity(
    date: str = Query(..., description="YYYY-MM-DD (IST)"),
    agent_id: Optional[str] = Query(default=None, description="Owner/manager only -- self is always allowed."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Every lead a human agent worked on this IST day. Owners/managers see
    every agent by default (or one via ?agent_id=); everyone else is always
    scoped to themselves, same rule dashboard_overview.py applies."""
    is_owner_view = current_user.role in (UserRole.OWNER, UserRole.MANAGER)
    scope_agent_id = agent_id if is_owner_view else current_user.id

    leads = lead_activity_service.get_lead_activity(db, current_user.tenant_id, date, agent_id=scope_agent_id)
    return {"date": date, "agent_id": scope_agent_id, "leads": leads}
