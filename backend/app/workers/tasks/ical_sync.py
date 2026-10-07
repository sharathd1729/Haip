"""
Read the outside calendars (Airbnb / Booking.com / Google ...) linked to a property.

Beat fans out every 30 minutes. OTAs refresh their own copy of HAIP's calendar
on their schedule (often hours), so polling faster than this buys nothing.
"""
from celery.exceptions import MaxRetriesExceededError
import structlog

from app.core.database import SessionLocal
from app.workers.celery_app import celery_app

log = structlog.get_logger()


@celery_app.task(name="ical.sync_all_feeds")
def sync_all_feeds():
    """Fan out -- one ical.sync_feed subtask per active feed that has an import URL."""
    from app.core.database import set_tenant_context
    from app.models.ical_feed import ICalFeed
    from app.models.tenant import Tenant
    db = SessionLocal()
    try:
        # ical_feeds is under RLS, so read it one tenant at a time.
        count = 0
        for (tenant_id,) in db.query(Tenant.id).filter(Tenant.is_active.is_(True)).all():
            set_tenant_context(db, tenant_id)
            ids = db.query(ICalFeed.id).filter(
                ICalFeed.tenant_id == tenant_id, ICalFeed.is_active.is_(True),
                ICalFeed.import_url_enc.isnot(None),
            ).all()
            for (feed_id,) in ids:
                sync_one_feed.apply_async(kwargs={"feed_id": str(feed_id), "tenant_id": str(tenant_id)},
                                          queue="call_ingest")
                count += 1
        log.info("ical_sync_fanned_out", count=count)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=2, default_retry_delay=120, name="ical.sync_feed")
def sync_one_feed(self, feed_id: str, tenant_id: str):
    """Import one feed. sync_feed records its own failures on the row and never
    raises, so a retry here only covers infrastructure errors (DB, broker)."""
    from app.core.database import set_tenant_context
    from app.models.ical_feed import ICalFeed
    from app.services import ical_sync_service

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        feed = db.query(ICalFeed).filter_by(id=feed_id, tenant_id=tenant_id).first()
        if not feed or not feed.is_active or not feed.import_url_enc:
            return
        ical_sync_service.sync_feed(db, feed)
    except Exception as exc:  # noqa: BLE001
        log.error("ical_sync_error", feed_id=feed_id, tenant_id=tenant_id, error=str(exc))
        try:
            raise self.retry(exc=exc)
        except MaxRetriesExceededError:
            log.error("ical_sync_retries_exhausted", feed_id=feed_id, tenant_id=tenant_id)
    finally:
        db.close()
