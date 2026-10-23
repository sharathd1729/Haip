"""Studio plan phase 2 Celery tasks. Exact-name routes in celery_app.py.

  marketing_research.signals_all          beat daily 05:30: queue collect_signals for workspaces with a source on
  marketing_research.collect_signals      Google / YouTube / Places / Keyword Planner / hashtags / audio (queue default)
  marketing_research.collect_all          beat Sunday 22:00: queue the collector for workspaces that switched it on
  marketing_research.collect_competitors  queue research_collect ONLY (the separate, opt-in, logged-out collector
                                          worker, docker-compose profile "research"); then competitor ads; then queues
                                          the video reader for kept Reels
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


@shared_task(name="marketing_research.collect_competitors")
def collect_competitors(tenant_id: str):
    from app.models.tenant import Tenant
    from app.services import marketing_research_sources as src
    from app.services import marketing_video_read as reader
    with SessionLocal() as db:
        tenant = db.query(Tenant).filter_by(id=tenant_id).one()
        out = src.collect_competitors(db, tenant, download=src.download_public)
        db.commit()
        try:
            out["ads"] = src.collect_ads(db, tenant)
            db.commit()
        except Exception as exc:  # noqa: BLE001 -- ads are a separate source; posts are already saved
            db.rollback()
            out["ads"] = f"failed: {type(exc).__name__}"
        to_read = reader.to_read(db, tenant_id) if src.ready(db, tenant, "video_reading") else []
    for post_id in to_read:
        read_video.delay(tenant_id, post_id)
    log.info("research_competitors_collected", tenant_id=tenant_id, posts=out.get("posts"), reads=len(to_read))
    return {k: v for k, v in out.items() if k != "errors"} | {"errors": len(out.get("errors", []))}


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
