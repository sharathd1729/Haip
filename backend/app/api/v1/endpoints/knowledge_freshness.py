"""What the bot knows -- freshness per source, "Re-index now", and the knowledge-source settings (owner/manager).

GET  /knowledge/freshness        per source: used by the bot / waiting approval / indexing / failed / out of date, last updated and
                                 indexed; business data published vs drafts; Instagram sync and website re-crawl state; warnings
POST /knowledge/refresh          re-index everything not indexed (or indexed from older wording) and read Instagram now (audited)
PUT  /knowledge/source-settings  auto_approve_social / social_sync / website_recrawl (audited, kb.settings_updated)

No LLM or external call runs in these handlers: refresh only queues Celery work (services/knowledge_freshness.py).
"""
from typing import Optional

import structlog

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.deps import require_module, require_roles
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import knowledge_freshness

log = structlog.get_logger()

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

_owner_or_manager = require_roles(UserRole.OWNER, UserRole.MANAGER)


class KnowledgeSourceSettings(BaseModel):
    auto_approve_social: Optional[bool] = None
    social_sync: Optional[bool] = None
    website_recrawl: Optional[bool] = None


def _tenant(db: Session, user: User) -> Tenant:
    tenant = db.query(Tenant).filter_by(id=user.tenant_id).first()
    if tenant is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return tenant


@router.get("/freshness")
def knowledge_freshness_report(
    current_user: User = Depends(_owner_or_manager),
    db: Session = Depends(get_db),
    _module=Depends(require_module("ai_concierge")),
):
    return knowledge_freshness.report(db, _tenant(db, current_user))


@router.post("/refresh")
def refresh_knowledge(
    current_user: User = Depends(_owner_or_manager),
    db: Session = Depends(get_db),
    _module=Depends(require_module("ai_concierge")),
):
    try:
        return knowledge_freshness.refresh(db, _tenant(db, current_user), current_user.id)
    except Exception as exc:  # broker down: the rows are already "pending" and the periodic sweep will pick them up
        if isinstance(exc, HTTPException):
            raise
        log.warning("kb_refresh_enqueue_failed", tenant_id=current_user.tenant_id, error=str(exc)[:300])
        raise HTTPException(status_code=503, detail="Could not start re-indexing right now. Try again in a minute.")


@router.put("/source-settings")
def update_knowledge_source_settings(
    body: KnowledgeSourceSettings,
    current_user: User = Depends(_owner_or_manager),
    db: Session = Depends(get_db),
    _module=Depends(require_module("ai_concierge")),
):
    return knowledge_freshness.update_settings(db, _tenant(db, current_user), current_user.id, body.model_dump(exclude_none=True))
