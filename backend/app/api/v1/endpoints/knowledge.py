"""Knowledge base management — the content the AI concierge answers from.

GET    /knowledge                 list entries (filterable)
POST   /knowledge                 create an entry
PATCH  /knowledge/{id}            update an entry
DELETE /knowledge/{id}            delete an entry (and its vector)
POST   /knowledge/{id}/reembed    force re-embedding
POST   /knowledge/search          retrieval preview -- "what would the AI find?"
GET    /knowledge/stats           counts by status, for the settings header
POST   /knowledge/upload          ingest a document (PDF/Word/text) -- pending review
POST   /knowledge/crawl           ingest website page(s) by URL -- pending review
"""

from typing import Optional
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
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
    KnowledgeCrawlRequest,
    KnowledgeIngestResult,
)
from app.services import knowledge_service, knowledge_ingest

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


@router.post("/upload", response_model=KnowledgeIngestResult, status_code=status.HTTP_201_CREATED)
async def upload_knowledge_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _cap=Depends(require_capability("settings.manage")),
    _module=Depends(require_module("ai_concierge")),
):
    """Ingest a document (PDF, Word, or plain text) into the knowledge
    base. The extracted content lands as one or more pending entries --
    a human must review and approve before the AI uses any of it, same
    gate scraped/mined content already goes through. The original file
    itself is stored in R2 (never Supabase storage) so it stays
    retrievable for reference."""
    import uuid as uuid_lib
    from app.services import media_storage

    filename = file.filename or "document"
    ext = Path(filename).suffix.lower()
    if ext not in knowledge_ingest.ALLOWED_UPLOAD_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Use PDF, Word (.docx), or plain text.",
        )

    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if len(content) > knowledge_ingest.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({size_mb:.1f} MB). Max {knowledge_ingest.MAX_UPLOAD_MB} MB.",
        )
    if not content:
        raise HTTPException(status_code=400, detail="File is empty.")

    try:
        text = knowledge_ingest.extract_text_from_upload(filename, file.content_type or "", content)
    except knowledge_ingest.IngestError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not text.strip():
        raise HTTPException(status_code=400, detail="Couldn't find any readable text in this file.")

    upload_id = str(uuid_lib.uuid4())
    file_key = media_storage.upload_knowledge_file(
        current_user.tenant_id, upload_id, content, file.content_type or "application/octet-stream", filename,
    )

    entries = knowledge_ingest.ingest_chunks(
        db, current_user.tenant_id, text,
        source="document", source_ref=filename, file_s3_key=file_key,
        created_by=current_user.id,
    )
    log.info("kb_document_uploaded", tenant_id=current_user.tenant_id, filename=filename, chunk_count=len(entries))
    return KnowledgeIngestResult(
        entries_created=len(entries),
        message=f"Added {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} from \"{filename}\" -- review and approve them below before the AI uses this content.",
    )


@router.post("/crawl", response_model=KnowledgeIngestResult, status_code=status.HTTP_201_CREATED)
def crawl_knowledge_urls(
    body: KnowledgeCrawlRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _cap=Depends(require_capability("settings.manage")),
    _module=Depends(require_module("ai_concierge")),
):
    """Ingest one or more web pages (e.g. your own site's FAQ or amenities
    page) into the knowledge base. Same pending-review gate as document
    upload -- nothing here is used by the AI until a human approves it."""
    # KnowledgeCrawlRequest's own max_length=5 already rejects more than
    # MAX_URLS_PER_REQUEST at the schema level (422) before this ever runs.
    urls = [u.strip() for u in body.urls if u.strip()]
    if not urls:
        raise HTTPException(status_code=422, detail="At least one URL is required.")

    total_entries = 0
    failures: list[str] = []
    for url in urls:
        try:
            text = knowledge_ingest.fetch_url_text(url)
        except knowledge_ingest.IngestError as exc:
            failures.append(str(exc))
            continue
        entries = knowledge_ingest.ingest_chunks(
            db, current_user.tenant_id, text,
            source="website", source_url=url, created_by=current_user.id,
        )
        total_entries += len(entries)

    if total_entries == 0:
        raise HTTPException(status_code=400, detail="; ".join(failures) or "Couldn't ingest any of the given URLs.")

    log.info(
        "kb_urls_crawled", tenant_id=current_user.tenant_id, url_count=len(urls),
        entries_created=total_entries, failure_count=len(failures),
    )
    message = f"Added {total_entries} entr{'y' if total_entries == 1 else 'ies'} from {len(urls) - len(failures)} page(s) -- review and approve them below before the AI uses this content."
    if failures:
        message += f" {len(failures)} page(s) failed: {'; '.join(failures)}"
    return KnowledgeIngestResult(entries_created=total_entries, message=message)


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
