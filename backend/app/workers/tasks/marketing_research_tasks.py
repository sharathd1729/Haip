"""Studio plan phase 2 + 3 Celery tasks (researcher, strategist). Exact-name routes in celery_app.py.
  marketing_strategy.write_doc            shoot brief / monthly deck text (router marketing_brief / marketing_deck)
  marketing_strategy.tick                 hourly: the 1st from 08:00 local, queue that month's deck once

  marketing_research.signals_all          beat daily 05:30: queue collect_signals for workspaces with a source on
  marketing_research.collect_signals      Google / YouTube / Places / Keyword Planner / hashtags / audio (queue default)
  marketing_research.collect_all          beat Sunday 22:00: queue the collector for workspaces that switched it on
  marketing_research.collect_competitors  queue research_collect ONLY (the separate, opt-in, logged-out collector
                                          worker, docker-compose profile "research", own env backend/.env.collector):
                                          public posts + competitor ads, raw rows and media only; then queue_reads
  marketing_research.queue_reads          normal worker: queue the video reader for kept Reels (AI never in the collector)
  marketing_research.read_video           one Reel into the swipe file (queue default)
  marketing_research.sweep_media          beat daily: delete kept competitor media past its retention
Never retried automatically: the next scheduled run picks up anything left; a failure is logged per source.
"""
import structlog
from celery import shared_task

from app.core.database import SessionLocal

log = structlog.get_logger()


def _tenants_with(db, keys: tuple[str, ...]):
    from app.services import marketing_research_sources as src
    from app.workers.tasks.marketing_insights import _studio_tenants
    return [t for t in _studio_tenants(db) if any(src.get_settings(t)[k] for k in keys)]


@shared_task(name="marketing_research.signals_all")
def signals_all():
    from app.services.marketing_research_sources import SOURCES
    keys = tuple(k for k in SOURCES if k not in ("collector", "ad_library", "video_reading"))
    with SessionLocal() as db:
        ids = [t.id for t in _tenants_with(db, keys)]
    for tid in ids:
        collect_signals.delay(tid)
    return {"queued": len(ids)}


@shared_task(name="marketing_research.collect_signals")
def collect_signals(tenant_id: str):
    from app.models.tenant import Tenant
    from app.services import marketing_research_sources as src
    with SessionLocal() as db:
        tenant = db.query(Tenant).filter_by(id=tenant_id).one()
        done = src.collect_signals(db, tenant)
        db.commit()
    log.info("research_signals_collected", tenant_id=tenant_id, sources=done)
    return done


@shared_task(name="marketing_research.collect_all")
def collect_all():
    with SessionLocal() as db:
        ids = [t.id for t in _tenants_with(db, ("collector", "ad_library"))]
    for tid in ids:
        collect_competitors.delay(tid)
    return {"queued": len(ids)}


def collector_run(db, tenant_id: str, *, download=None) -> dict:
    """What the isolated collector does: public data in, raw rows and media out. No AI, no tenant token (it runs with
    backend/.env.collector, which has no ENCRYPTION_KEY and no AI keys); reading the videos is queued for the normal
    worker (`marketing_research.queue_reads`)."""
    from app.models.tenant import Tenant
    from app.services import marketing_research_sources as src
    tenant = db.query(Tenant).filter_by(id=tenant_id).one()
    out = src.collect_competitors(db, tenant, download=download)
    db.commit()
    try:
        out["ads"] = src.collect_ads(db, tenant)
        db.commit()
    except Exception as exc:  # noqa: BLE001 -- ads are a separate source; posts are already saved
        db.rollback()
        out["ads"] = f"failed: {type(exc).__name__}"
    queue_reads.delay(tenant_id)
    return {k: v for k, v in out.items() if k != "errors"} | {"errors": len(out.get("errors", []))}


@shared_task(name="marketing_research.collect_competitors")
def collect_competitors(tenant_id: str):
    from app.services import marketing_research_sources as src
    with SessionLocal() as db:
        out = collector_run(db, tenant_id, download=src.download_public)
    log.info("research_competitors_collected", tenant_id=tenant_id, posts=out.get("posts"))
    return out


@shared_task(name="marketing_research.queue_reads")
def queue_reads(tenant_id: str):
    """On the normal worker (it has the AI keys): queue the video reader for newly kept Reels."""
    from app.models.tenant import Tenant
    from app.services import marketing_research_sources as src
    from app.services import marketing_video_read as reader
    with SessionLocal() as db:
        tenant = db.query(Tenant).filter_by(id=tenant_id).one()
        ids = reader.to_read(db, tenant_id) if src.ready(db, tenant, "video_reading") else []
    for post_id in ids:
        read_video.delay(tenant_id, post_id)
    return {"queued": len(ids)}


@shared_task(name="marketing_research.read_video")
def read_video(tenant_id: str, post_id: str):
    from app.models.tenant import Tenant
    from app.services import marketing_video_read as reader
    with SessionLocal() as db:
        tenant = db.query(Tenant).filter_by(id=tenant_id).one()
        item = reader.read_post(db, tenant, post_id)
        db.commit()
        return {"status": item.status}


@shared_task(name="marketing_research.sweep_media")
def sweep_media():
    from app.services import marketing_research_sources as src
    with SessionLocal() as db:
        n = src.sweep_media(db)
        db.commit()
    return {"deleted": n}


# ── Strategist (studio plan phase 3) ───────────────────────────────────────────────────────────────────────────────

@shared_task(name="marketing_strategy.write_doc", bind=True, max_retries=2)
def write_doc(self, tenant_id: str, doc_id: str):
    """A shoot brief or a monthly deck. Only a transient provider error is retried (the deck never needs it: it falls
    back to its deterministic text)."""
    from app.models.marketing_research import MarketingStrategyDoc
    from app.services import marketing_ai_service as ai
    from app.services import marketing_strategy as strategy
    with SessionLocal() as db:
        try:
            doc = strategy.write(db, tenant_id, doc_id)
            db.commit()
            return {"status": doc.status}
        except ai.LLMTransientError as exc:
            db.rollback()
            if self.request.retries < 2:
                raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))
            doc = db.query(MarketingStrategyDoc).filter_by(id=doc_id, tenant_id=tenant_id).one()
            doc.status, doc.error = "failed", f"The AI is unavailable right now: {exc}"[:2000]
            db.commit()
            return {"status": "failed"}


@shared_task(name="marketing_strategy.tick")
def strategy_tick():
    """Hourly: on the 1st from 08:00 workspace time, write that month's strategy deck once."""
    from app.core import tenant_tz
    from app.models.tenant import Tenant
    from app.services import marketing_strategy as strategy
    with SessionLocal() as db:
        due = strategy.due_decks(db, tenant_tz.get_tenant_now)
        ids = []
        for tid, month in due:
            tenant = db.query(Tenant).filter_by(id=tid).one()
            ids.append((tid, strategy.request_deck(db, tenant, month, None).id))
        db.commit()
    for tid, doc_id in ids:
        write_doc.delay(tid, doc_id)
    return {"queued": len(ids)}
