"""Knowledge base management — the content the AI concierge answers from.

GET    /knowledge                 list entries (filterable)
POST   /knowledge                 create an entry
PATCH  /knowledge/{id}            update an entry
DELETE /knowledge/{id}            delete an entry (and its vector)
POST   /knowledge/{id}/reembed    force re-embedding
POST   /knowledge/search          retrieval preview -- "what would the AI find?"
GET    /knowledge/stats           counts by status + indexing health, for the settings header
POST   /knowledge/reindex         retry every entry that is waiting or failed
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
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeCrawlRequest,
    KnowledgeIngestResult,
)
from app.services import knowledge_service, knowledge_ingest

log = structlog.get_logger()

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _require_own_property(db: Session, tenant_id: str, property_id: Optional[str]) -> None:
    """An entry may only be scoped to one of THIS tenant's properties (the column is a plain foreign key)."""
    if not property_id:
        return
    from app.models.property import Property
    if db.query(Property.id).filter_by(id=property_id, tenant_id=tenant_id).first() is None:
        raise HTTPException(status_code=422, detail="Unknown property")


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
    return knowledge_service.index_health(db, current_user.tenant_id)


@router.post("/reindex")
def reindex_all(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _cap=Depends(require_capability("settings.manage")),
    _module=Depends(require_module("ai_concierge")),
):
    """Retry every entry that is waiting to be indexed or failed. Runs in the background; the stats show progress."""
    waiting = db.query(KnowledgeEntry).filter(
        KnowledgeEntry.tenant_id == current_user.tenant_id,
        KnowledgeEntry.is_active.is_(True),
        KnowledgeEntry.embedding_status.in_(["pending", "failed"]),
    ).count()
    if waiting:
        try:
            from app.workers.tasks.embed_knowledge import embed_pending
            embed_pending.apply_async(kwargs={"tenant_id": current_user.tenant_id, "limit": 200, "force": True})
        except Exception as exc:
            log.warning("kb_reindex_enqueue_failed", tenant_id=current_user.tenant_id, error=str(exc))
            raise HTTPException(status_code=503, detail="Could not start indexing right now. Try again in a minute.")
    return {"queued": waiting}


@router.post("", response_model=KnowledgeEntryOut, status_code=status.HTTP_201_CREATED)
def create_entry(
    body: KnowledgeEntryCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _cap=Depends(require_capability("settings.manage")),
    _module=Depends(require_module("ai_concierge")),
):
    _require_own_property(db, current_user.tenant_id, body.property_id)
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

    report = knowledge_ingest.ingest_chunks_report(
        db, current_user.tenant_id, text,
        source="document", source_ref=filename, file_s3_key=file_key,
        created_by=current_user.id,
    )
    n = len(report.created)
    log.info("kb_document_uploaded", tenant_id=current_user.tenant_id, filename=filename, chunk_count=n, unchanged=report.unchanged)
    return KnowledgeIngestResult(
        entries_created=n,
        unchanged=report.unchanged,
        marked_out_of_date=report.marked_out_of_date,
        message=_ingest_message(f"\"{filename}\"", report),
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

    total_entries = unchanged = out_of_date = fetched = 0
    failures: list[str] = []
    for url in urls:
        try:
            text = knowledge_ingest.fetch_url_text(url)
        except knowledge_ingest.IngestError as exc:
            failures.append(str(exc))
            continue
        report = knowledge_ingest.ingest_chunks_report(
            db, current_user.tenant_id, text,
            source="website", source_url=url, created_by=current_user.id,
        )
        fetched += 1
        total_entries += len(report.created)
        unchanged += report.unchanged
        out_of_date += report.marked_out_of_date

    if fetched == 0:
        raise HTTPException(status_code=400, detail="; ".join(failures) or "Couldn't ingest any of the given URLs.")

    log.info(
        "kb_urls_crawled", tenant_id=current_user.tenant_id, url_count=len(urls),
        entries_created=total_entries, failure_count=len(failures),
    )
    message = _ingest_message(f"{fetched} page(s)", knowledge_ingest.IngestReport(
        created=[None] * total_entries, unchanged=unchanged, marked_out_of_date=out_of_date))
    if failures:
        message += f" {len(failures)} page(s) failed: {'; '.join(failures)}"
    return KnowledgeIngestResult(
        entries_created=total_entries, message=message, unchanged=unchanged, marked_out_of_date=out_of_date,
    )


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

    sent = body.model_fields_set
    if "property_id" in sent:
        # Explicit null = "applies to every property". Anything else must be one of this tenant's properties.
        _require_own_property(db, current_user.tenant_id, body.property_id)
        entry.property_id = body.property_id or None
    if "question" in sent:
        entry.question = (body.question or "").strip() or None
    for field in ("category", "content", "priority", "is_active", "review_status"):
        val = getattr(body, field)
        if val is not None:
            setattr(entry, field, val.strip() if field == "content" else val)
    if body.keep_out_of_date:
        entry.stale_since = None

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
        # From here until indexing finishes the entry is NOT retrievable (retrieval requires "done"), so the AI can never
        # answer from the old wording after an edit; it simply does not use the entry until the new wording is indexed.
        entry.embedding_status = "pending"
        entry.embedding_error = None
        entry.embedding_attempts = 0
        if "content" in sent or "question" in sent:
            entry.stale_since = None      # the owner just touched it: it is current by definition
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
    entry.embedding_attempts = 0
    db.commit()
    db.refresh(entry)
    _queue_embed(entry.tenant_id, entry.id)
    return KnowledgeEntryOut.model_validate(entry)


_SEARCH_MESSAGES = {
    "no_match": "Nothing in your active, indexed knowledge matches this question.",
    "embedding_unavailable": "The search service did not respond, so this could not be checked. Try again in a minute.",
    "search_failed": "The knowledge search failed. The AI would answer without knowledge until this is fixed.",
    "unsupported": "Knowledge search is not available on this deployment (needs PostgreSQL with pgvector).",
}


def _ingest_message(what: str, report) -> str:
    n = len(report.created)
    parts = []
    if n:
        parts.append(f"Added {n} new entr{'y' if n == 1 else 'ies'} from {what} -- review and approve them below before the AI uses this content.")
    else:
        parts.append(f"Nothing new in {what}.")
    if report.unchanged:
        parts.append(f"{report.unchanged} passage(s) were already in your knowledge base and were not added again.")
    if report.marked_out_of_date:
        parts.append(
            f"{report.marked_out_of_date} earlier passage(s) from the same source are no longer in it; they are marked out of "
            "date and the AI will not use them (keep any you still want)."
        )
    return " ".join(parts)


@router.post("/search", response_model=KnowledgeSearchResponse)
def search_knowledge(
    body: KnowledgeSearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    _module=Depends(require_module("ai_concierge")),
):
    """Retrieval preview: shows exactly what the concierge would pull for a given guest question. It calls the SAME retrieval
    function a real reply uses; pass `conversation_id` to also use that conversation's property, as a reply does."""
    property_id = body.property_id
    if body.conversation_id:
        from app.models.conversation import Conversation
        conv = db.query(Conversation).filter_by(id=body.conversation_id, tenant_id=current_user.tenant_id).first()
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        property_id = conv.property_id
    else:
        _require_own_property(db, current_user.tenant_id, property_id)

    outcome = knowledge_service.search_detailed(
        db, current_user.tenant_id, body.query, property_id=property_id, top_k=body.top_k,
    )
    health = knowledge_service.index_health(db, current_user.tenant_id)
    message = _SEARCH_MESSAGES.get(outcome.status, "")
    if outcome.status == "no_match" and (health["embedding_pending"] or health["embedding_failed"]):
        message += (
            f" {health['embedding_pending']} entr{'y is' if health['embedding_pending'] == 1 else 'ies are'} still being indexed"
            f" and {health['embedding_failed']} failed to index; those cannot be found until indexing succeeds."
        )
    return KnowledgeSearchResponse(
        query=body.query,
        hits=[KnowledgeSearchHit(**h) for h in outcome.hits],
        status=outcome.status,
        message=message,
        property_id=property_id,
        retrievable_count=health["retrievable"],
    )
