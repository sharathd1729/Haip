"""Embedding worker for knowledge base entries.

Embedding is a network call to NVIDIA NIM, so it never runs inline in a
request handler (CLAUDE.md). Endpoints write the row with
`embedding_status="pending"` and enqueue here; the entry becomes retrievable
only once this task marks it "done".
"""

import structlog
from celery import shared_task

from datetime import datetime, timezone

from app.core.database import SessionLocal, set_tenant_context
from app.models.knowledge import KnowledgeEntry
from app.services import knowledge_service

log = structlog.get_logger()


def _ensure_phrasings(db, entry: KnowledgeEntry) -> None:
    """Generate alternate phrasings once per content revision.

    Regenerated only when the embedded text actually changed, so toggling
    is_active or editing a category never burns a generation call. Failures
    are non-fatal: an entry without phrasings still works, it just matches
    fewer wordings.
    """
    if entry.alt_phrasings and not knowledge_service.needs_reembed(entry):
        return
    try:
        from app.services.phrasing_service import generate_phrasings_sync
        phrasings = generate_phrasings_sync(entry.question, entry.content, n=6)
    except Exception as exc:
        log.warning("kb_phrasings_failed", entry_id=entry.id, error=str(exc))
        return
    if not phrasings:
        return
    entry.alt_phrasings = phrasings
    entry.alt_phrasings_generated_at = datetime.now(timezone.utc)
    db.commit()
    log.info("kb_phrasings_generated", entry_id=entry.id, count=len(phrasings))


@shared_task(name="knowledge.embed_entry", bind=True, max_retries=3)
def embed_entry(self, tenant_id: str, entry_id: str):
    """Embed a single entry. Retries on transient failure."""
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        entry = (
            db.query(KnowledgeEntry)
            .filter_by(id=entry_id, tenant_id=tenant_id)
            .first()
        )
        if not entry:
            log.warning("kb_embed_entry_missing", entry_id=entry_id, tenant_id=tenant_id)
            return {"entry_id": entry_id, "status": "missing"}

        _ensure_phrasings(db, entry)
        ok = knowledge_service.embed_entry(db, entry)
        if not ok and self.request.retries < self.max_retries:
            # embed_entry() already recorded the failure on the row; retry with
            # backoff in case the provider was briefly unavailable.
            raise self.retry(countdown=30 * (self.request.retries + 1))
        return {"entry_id": entry_id, "status": "done" if ok else "failed"}
    finally:
        db.close()


@shared_task(name="knowledge.embed_pending")
def embed_pending(tenant_id: str, limit: int = 200):
    """Embed every entry for a tenant that is pending or stale.

    Used after bulk ingestion (website crawl, document upload) and as the
    retry path for entries whose embedding previously failed.
    """
    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        candidates = (
            db.query(KnowledgeEntry)
            .filter(
                KnowledgeEntry.tenant_id == tenant_id,
                KnowledgeEntry.is_active.is_(True),
                KnowledgeEntry.embedding_status.in_(["pending", "failed"]),
            )
            .limit(limit)
            .all()
        )
        done = 0
        for entry in candidates:
            if knowledge_service.embed_entry(db, entry):
                done += 1
        log.info("kb_embed_pending_done", tenant_id=tenant_id, attempted=len(candidates), succeeded=done)
        return {"tenant_id": tenant_id, "attempted": len(candidates), "succeeded": done}
    finally:
        db.close()
