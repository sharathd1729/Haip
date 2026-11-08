"""Google surfaces pulls (services/google_surfaces_sync.py). Queue: default (exact-name routes in celery_app.py).

  google_surfaces.pull_all          daily 07:10 IST: one pull_tenant per workspace with Google Business or Search Console
  google_surfaces.pull_tenant       Business Profile metrics + Search Console; re-queues itself (+60 s) while the Search
                                    Console backfill remains. Quota / other failures back off inside the service state.
  google_surfaces.pagespeed_all     weekly, Monday 05:40 IST: one pagespeed_tenant per workspace with a live website
  google_surfaces.pagespeed_tenant  home + top stay pages, mobile + desktop; a quota answer retries once in 6 h
One transaction per tenant (audit chain rule); token / key text never logged.
"""

import structlog
from celery import shared_task

from app.core.database import SessionLocal

log = structlog.get_logger()

BACKFILL_COUNTDOWN = 60
QUOTA_COUNTDOWN = 6 * 3600


@shared_task(name="google_surfaces.pull_all")
def pull_all():
    from app.services import google_surfaces_sync as sync

    with SessionLocal() as db:
        ids = sync.tenants_to_pull(db)
    for tid in ids:
        pull_tenant.delay(tid)
    return {"queued": len(ids)}


@shared_task(name="google_surfaces.pull_tenant")
def pull_tenant(tenant_id: str):
    from app.services import google_surfaces_sync as sync
    from app.services.business_data_service import tenant_today

    out: dict = {}
    with SessionLocal() as db:
        today = tenant_today(db, tenant_id)
        for name, fn in (("business_profile", sync.pull_gbp), ("search_console", sync.pull_gsc)):
            try:
                out[name] = fn(db, tenant_id, today)
                db.commit()
            except sync.Skipped as s:
                db.rollback()
                out[name] = {"skipped": str(s)}
            except Exception:  # noqa: BLE001 -- one source failing never stops the other
                db.rollback()
                log.exception("google_surfaces_pull_crashed", tenant_id=tenant_id, source=name)
                out[name] = {"failed": True}
    if (out.get("search_console") or {}).get("more"):
        pull_tenant.apply_async(args=[tenant_id], countdown=BACKFILL_COUNTDOWN)
    log.info(
        "google_surfaces_pulled",
        tenant_id=tenant_id,
        **{k: {kk: vv for kk, vv in v.items() if kk != "status"} for k, v in out.items()},
    )
    return out


@shared_task(name="google_surfaces.pagespeed_all")
def pagespeed_all():
    from app.core.config import settings
    from app.models.website import Site

    if not settings.PAGESPEED_API_KEY:
        log.info("pagespeed_skipped_no_key")
        return {"skipped": "no_key"}
    with SessionLocal() as db:
        ids = sorted({t for (t,) in db.query(Site.tenant_id).filter(Site.status == "live")})
    for tid in ids:
        pagespeed_tenant.delay(tid)
    return {"queued": len(ids)}


@shared_task(name="google_surfaces.pagespeed_tenant", bind=True, max_retries=1)
def pagespeed_tenant(self, tenant_id: str):
    from app.models.tenant import Tenant
    from app.models.website import Site
    from app.services import google_surfaces_sync as sync
    from app.services.business_data_service import tenant_today

    with SessionLocal() as db:
        tenant = db.get(Tenant, tenant_id)
        site = db.query(Site).filter_by(tenant_id=tenant_id, status="live").first()
        try:
            out = sync.pull_pagespeed(db, tenant, site, tenant_today(db, tenant_id))
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("pagespeed_crashed", tenant_id=tenant_id)
            return {"failed": True}
    if out.get("quota") and self.request.retries < self.max_retries:
        raise self.retry(countdown=QUOTA_COUNTDOWN)
    return out
