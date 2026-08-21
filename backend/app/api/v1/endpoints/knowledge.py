"""Knowledge base management — the content the AI concierge answers from.

GET    /knowledge                 list entries (filterable)
POST   /knowledge                 create an entry
PATCH  /knowledge/{id}            update an entry
DELETE /knowledge/{id}            delete an entry (and its vector)
POST   /knowledge/{id}/reembed    force re-embedding
POST   /knowledge/search          retrieval preview -- "what would the AI find?"
GET    /knowledge/stats           counts by status, for the settings header
"""

from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user, require_module
from app.core.database import get_db
from app.services.authz_service import require_capability
from app.models.knowledge import KnowledgeEntry
from app.models.user import User
from app.schemas.knowledge import (
    KnowledgeEntryCreate,
    KnowledgeEntryList,
    KnowledgeEntryOut,
    KnowledgeEntryUpdate,
    KnowledgeSearchHit,
    KnowledgeSearchResponse,
)
from app.services import knowledge_service

log = structlog.get_logger()

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _queue_embed(tenant_id: str, entry_id: str) -> None:
    """Enqueue embedding. Never let a broker hiccup fail the write -- the row
    stays `pending` and `POST /knowledge/{id}/reembed` (or the periodic
    embed_pending sweep) will pick it up."""
    try:
        from app.workers.tasks.embed_knowledge import embed_entry as embed_task
        embed_task.delay(tenant_id, entry_id)
    except Exception as exc:
        log.warning("kb_embed_enqueue_failed", entry_id=entry_id, tenant_id=tenant_id, error=str(exc))


@router.get("", response_model=KnowledgeEntryList)
def list_entries(
    category: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    review_status: Optional[str] = Query(None),
    search: Optional[str] = Query(None, description="Plain substring filter, not semantic"),
    include_inactive: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _module=Depends(require_module("ai_concierge")),
):
    q = db.query(KnowledgeEntry).filter(KnowledgeEntry.tenant_id == current_user.tenant_id)
    if not include_inactive:
        q = q.filter(KnowledgeEntry.is_active.is_(True))
    if category:
        q = q.filter(KnowledgeEntry.category == category)
    if source:
        q = q.filter(KnowledgeEntry.source == source)
    if review_status:
        q = q.filter(KnowledgeEntry.review_status == review_status)
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(KnowledgeEntry.content.ilike(like) | KnowledgeEntry.question.ilike(like))

    total = q.count()
    rows = (
        q.order_by(KnowledgeEntry.priority.desc(), KnowledgeEntry.updated_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return KnowledgeEntryList(items=[KnowledgeEntryOut.model_validate(r) for r in rows], total=total)


@router.get("/stats")
def knowledge_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _module=Depends(require_module("ai_concierge")),
):
    tid = current_user.tenant_id
    base = db.query(KnowledgeEntry).filter(KnowledgeEntry.tenant_id == tid)
    return {
        "total": base.count(),
        "active": base.filter(KnowledgeEntry.is_active.is_(True)).count(),
        "pending_review": base.filter(KnowledgeEntry.review_status == "pending").count(),
        "embedding_pending": base.filter(KnowledgeEntry.embedding_status == "pending").count(),
        "embedding_failed": base.filter(KnowledgeEntry.embedding_status == "failed").count(),
        # The number that actually matters: what the concierge can retrieve.
        "retrievable": base.filter(
            KnowledgeEntry.is_active.is_(True),
            KnowledgeEntry.review_status == "approved",
            KnowledgeEntry.embedding_status == "done",
        ).count(),
    }


@router.post("", response_model=KnowledgeEntryOut, status_code=status.HTTP_201_CREATED)
def create_entry(
    body: KnowledgeEntryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _cap=Depends(require_capability("settings.manage")),
    _module=Depends(require_module("ai_concierge")),
):
    entry = KnowledgeEntry(
        tenant_id=current_user.tenant_id,
        category=body.category,
        question=(body.question or None),
        content=body.content.strip(),
        property_id=body.property_id,
        source="manual",
        source_url=body.source_url,
        priority=body.priority,
        is_active=True,
        # Authored by a human on the tenant's team -- live immediately, unlike
        # scraped or conversation-mined content.
        review_status="approved",
        embedding_status="pending",
        created_by=current_user.id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    _queue_embed(entry.tenant_id, entry.id)
    log.info("kb_entry_created", entry_id=entry.id, tenant_id=entry.tenant_id, category=entry.category)
    return KnowledgeEntryOut.model_validate(entry)


@router.patch("/{entry_id}", response_model=KnowledgeEntryOut)
def update_entry(
    entry_id: str,
    body: KnowledgeEntryUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _cap=Depends(require_capability("settings.manage")),
    _module=Depends(require_module("ai_concierge")),
):
    entry = (
        db.query(KnowledgeEntry)
        .filter_by(id=entry_id, tenant_id=current_user.tenant_id)
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")

    for field in ("category", "question", "content", "property_id", "priority", "is_active", "review_status"):
        val = getattr(body, field)
        if val is not None:
            setattr(entry, field, val.strip() if field == "content" else val)

    # Editing phrasings is an explicit override -- the entry keeps exactly
    # what the tenant left, and _ensure_phrasings won't regenerate over it
    # unless the content itself changes.
    phrasings_changed = False
    if body.alt_phrasings is not None:
        cleaned = [p.strip() for p in body.alt_phrasings if p and p.strip()]
        phrasings_changed = cleaned != list(entry.alt_phrasings or [])
        entry.alt_phrasings = cleaned

    # Only re-embed when the embedded text actually changed; toggling
    # is_active or review_status must not burn an embedding call. Phrasings
    # each carry their own vector, so editing them changes what is stored
    # even though the content hash is unaffected -- without this, a deleted
    # phrasing would keep matching from its stale vector.
    stale = knowledge_service.needs_reembed(entry) or phrasings_changed
    if stale:
        entry.embedding_status = "pending"
    db.commit()
    db.refresh(entry)
    if stale:
        _queue_embed(entry.tenant_id, entry.id)
    return KnowledgeEntryOut.model_validate(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_entry(
    entry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _cap=Depends(require_capability("settings.manage")),
    _module=Depends(require_module("ai_concierge")),
):
    entry = (
        db.query(KnowledgeEntry)
        .filter_by(id=entry_id, tenant_id=current_user.tenant_id)
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    knowledge_service.delete_vector(db, entry.tenant_id, entry.id)
    db.delete(entry)
    db.commit()
    log.info("kb_entry_deleted", entry_id=entry_id, tenant_id=current_user.tenant_id)
    return None


@router.post("/{entry_id}/reembed", response_model=KnowledgeEntryOut)
def reembed_entry(
    entry_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _cap=Depends(require_capability("settings.manage")),
    _module=Depends(require_module("ai_concierge")),
):
    entry = (
        db.query(KnowledgeEntry)
        .filter_by(id=entry_id, tenant_id=current_user.tenant_id)
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Knowledge entry not found")
    entry.embedding_status = "pending"
    entry.embedding_error = None
    db.commit()
    db.refresh(entry)
    _queue_embed(entry.tenant_id, entry.id)
    return KnowledgeEntryOut.model_validate(entry)


@router.post("/search", response_model=KnowledgeSearchResponse)
def search_knowledge(
    body: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _module=Depends(require_module("ai_concierge")),
):
    """Retrieval preview: shows exactly what the concierge would pull for a
    given guest question. This is the tenant's way to sanity-check the KB
    without waiting for a real guest to ask."""
    query = (body or {}).get("query", "")
    if not str(query).strip():
        raise HTTPException(status_code=422, detail="query is required")
    property_id = (body or {}).get("property_id")
    top_k = int((body or {}).get("top_k") or 5)

    hits = knowledge_service.search(
        db, current_user.tenant_id, str(query), property_id=property_id, top_k=max(1, min(top_k, 20))
    )
    return KnowledgeSearchResponse(
        query=str(query),
        hits=[KnowledgeSearchHit(**h) for h in hits],
    )
