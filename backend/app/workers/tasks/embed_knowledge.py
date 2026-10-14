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


# Stop a sweep after this many entries fail in a row: the provider is down, and every further attempt would only fail too.
_CIRCUIT_BREAKER = 3


def _due(entry: KnowledgeEntry, now: datetime, min_age_seconds: int, force: bool) -> bool:
    """Whether the periodic sweep should (re)try this entry now."""
    if force:
        return True
    updated = entry.updated_at
    if updated is not None and updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    age = (now - updated).total_seconds() if updated else 10**9
    if entry.embedding_status == "pending":
        return age >= min_age_seconds
    attempts = int(entry.embedding_attempts or 0)
    if attempts >= knowledge_service.MAX_AUTO_ATTEMPTS:
        return False            # gave up on its own; a person can force a retry from the settings page
    return age >= min(60, 5 * 2 ** attempts) * 60   # 10, 20, 40, 60, 60 ... minutes between automatic retries


@shared_task(name="knowledge.embed_pending")
def embed_pending(tenant_id: str, limit: int = 200, min_age_seconds: int = 0, force: bool = False):
    """Embed every entry for a tenant that is pending or failed.

    Used after bulk ingestion, as the periodic safety net (a task lost to a broker blip or a worker restart used to leave an
    entry "pending" -- invisible to the AI -- until someone clicked Re-index), and for a manual "retry failed" click
    (`force=True`, which ignores backoff and the attempt cap).
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
            .order_by(KnowledgeEntry.updated_at.asc())
            .limit(limit)
            .all()
        )
        now = datetime.now(timezone.utc)
        due = [e for e in candidates if _due(e, now, min_age_seconds, force)]
        done = failed_in_a_row = attempted = 0
        for entry in due:
            attempted += 1
            if knowledge_service.embed_entry(db, entry):
                done += 1
                failed_in_a_row = 0
                continue
            failed_in_a_row += 1
            if failed_in_a_row >= _CIRCUIT_BREAKER:
                log.warning("kb_embed_sweep_stopped_provider_failing", tenant_id=tenant_id, attempted=attempted)
                break
        log.info("kb_embed_pending_done", tenant_id=tenant_id, candidates=len(candidates), attempted=attempted, succeeded=done)
        return {"tenant_id": tenant_id, "attempted": attempted, "succeeded": done}
    finally:
        db.close()


@shared_task(name="knowledge.sweep_all_tenants")
def sweep_all_tenants():
    """Beat entry point (celery_app.py "knowledge-index-sweep"): fan out to every active tenant."""
    from app.models.tenant import Tenant

    db = SessionLocal()
    try:
        tenant_ids = [t.id for t in db.query(Tenant).filter(Tenant.is_active.is_(True)).all()]
    finally:
        db.close()
    for tid in tenant_ids:
        embed_pending.apply_async(kwargs={"tenant_id": tid, "limit": 50, "min_age_seconds": 120})
    return {"tenants_queued": len(tenant_ids)}
