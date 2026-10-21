"""Performance marketer tasks (agency M5). Queue: whatsapp (exact-name routes in celery_app.py, next to meta_ads.*).

marketing_ads.push            put one approved ad draft on Meta (retries a Meta outage / rate limit, 4x)
marketing_ads.evaluate_all    hourly: per tenant -> evaluate_tenant
marketing_ads.evaluate_tenant boost rules + the spend watchdog for one tenant (one transaction per tenant)
marketing_capi.sweep_all      hourly: per tenant with the Conversions API on -> send_tenant
marketing_capi.send_tenant    send that tenant's new bookings as Purchase events
marketing_reports.weekly_all  Monday morning: the weekly marketing report email (agency M6), where the owner turned it on
"""
import structlog
from celery import shared_task

from app.core.database import SessionLocal

log = structlog.get_logger()

PUSH_RETRIES = 4


def _queue_push(tenant_id: str, draft_id: str) -> None:
    try:
        push.delay(tenant_id, draft_id)
    except Exception as exc:  # noqa: BLE001  the hourly check picks approved drafts up again
        log.warning("marketing_ad_push_not_queued", tenant_id=tenant_id, draft_id=draft_id, error=str(exc)[:200])


@shared_task(name="marketing_ads.push", bind=True, max_retries=PUSH_RETRIES)
def push(self, tenant_id: str, draft_id: str):
    from app.services import marketing_ads_push as pusher
    with SessionLocal() as db:
        try:
            pusher.push(db, tenant_id, draft_id)
        except pusher.TransientPushError as exc:
            if self.request.retries < PUSH_RETRIES:
                raise self.retry(exc=exc, countdown=300 * (2 ** self.request.retries))
            draft = pusher.ads.get_draft(db, tenant_id, draft_id)
            draft.status, draft.error = "failed", f"Meta kept refusing for an hour: {exc}"[:2000]
            db.commit()


def _ads_tenants(db) -> list[str]:
    from app.models.marketing_ads import MarketingAdDraft, MarketingBoostRule
    ids = {t for (t,) in db.query(MarketingBoostRule.tenant_id).filter_by(status="approved").distinct()}
    ids |= {t for (t,) in db.query(MarketingAdDraft.tenant_id).filter(
        MarketingAdDraft.status.in_(("live", "approved"))).distinct()}
    return sorted(ids)


@shared_task(name="marketing_ads.evaluate_all")
def evaluate_all():
    with SessionLocal() as db:
        tenants = _ads_tenants(db)
    for tid in tenants:
        evaluate_tenant.delay(tid)
    return {"tenants": len(tenants)}


@shared_task(name="marketing_ads.evaluate_tenant")
def evaluate_tenant(tenant_id: str):
    from app.models.marketing_ads import MarketingAdDraft
    from app.models.tenant import Tenant
    from app.services import marketing_ads_push as pusher
    from app.services import marketing_boost as boost
    with SessionLocal() as db:
        tenant = db.query(Tenant).filter_by(id=tenant_id).one()
        try:
            watched = pusher.watch(db, tenant)
        except Exception as exc:  # noqa: BLE001  the Meta account may be disconnected; rules still report
            db.rollback()
            watched = {"error": str(exc)[:200]}
        results = boost.evaluate(db, tenant, queue_push=_queue_push)
        stuck = [d.id for d in db.query(MarketingAdDraft).filter_by(tenant_id=tenant_id, status="approved")]
        for draft_id in stuck:                 # approved but never pushed (queue was down): try again
            _queue_push(tenant_id, draft_id)
    return {"watch": watched, "rules": len(results), "requeued": len(stuck)}


@shared_task(name="marketing_capi.sweep_all")
def capi_sweep_all():
    from app.models.tenant import Tenant
    from app.services import marketing_ads_service as ads
    with SessionLocal() as db:
        tenants = [t.id for t in db.query(Tenant).all() if ads.get_settings(t)["capi_enabled"]]
    for tid in tenants:
        capi_send_tenant.delay(tid)
    return {"tenants": len(tenants)}


@shared_task(name="marketing_capi.send_tenant")
def capi_send_tenant(tenant_id: str):
    from app.models.tenant import Tenant
    from app.services import marketing_capi
    with SessionLocal() as db:
        return marketing_capi.send_tenant(db, db.query(Tenant).filter_by(id=tenant_id).one())


@shared_task(name="marketing_reports.weekly_all")
def weekly_reports_all():
    from app.models.tenant import Tenant
    from app.services import marketing_reports
    with SessionLocal() as db:
        tenants = [t.id for t in db.query(Tenant).all() if marketing_reports.settings_of(t)["weekly_email"]]
    for tid in tenants:
        weekly_report_tenant.delay(tid)
    return {"tenants": len(tenants)}


@shared_task(name="marketing_reports.weekly_tenant")
def weekly_report_tenant(tenant_id: str):
    from app.models.tenant import Tenant
    from app.services import marketing_reports
    with SessionLocal() as db:
        return marketing_reports.send_weekly(db, db.query(Tenant).filter_by(id=tenant_id).one())
