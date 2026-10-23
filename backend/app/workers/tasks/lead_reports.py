"""The daily lead report email + the "update your leads" reminder (lead_report_email.py).

  lead_reports.daily_email_tick   beat every 5 minutes: every active workspace that switched it on gets, once per IST day,
                                  the reminder 30 minutes before its send time (default 10:30) and the email at the send time
                                  (default 11:00). Queue ai_scoring, like the other report emails (exact-name route).
One transaction per workspace (a transaction never audits two tenants).
"""
import structlog
from celery import shared_task

from app.core.config import settings
from app.core.database import SessionLocal, set_tenant_context

log = structlog.get_logger()


@shared_task(name="lead_reports.daily_email_tick")
def daily_email_tick():
    from app.models.tenant import Tenant
    from app.services import lead_report_email

    db = SessionLocal()
    out = {}
    try:
        tenants = [t for t in db.query(Tenant).filter(Tenant.is_active.is_(True)).all() if lead_report_email.settings_of(t)["enabled"]]
        for tenant in tenants:
            try:
                set_tenant_context(db, tenant.id)
                out[tenant.id] = lead_report_email.tick(db, tenant, app_url=(settings.FRONTEND_URL or "").rstrip("/"))["status"]
            except Exception as exc:     # one workspace's failure must not skip the rest
                db.rollback()
                log.warning("daily_lead_email_tick_failed", tenant_id=tenant.id, error=str(exc)[:300])
        return out
    finally:
        db.close()
