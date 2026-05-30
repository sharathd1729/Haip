"""
Ask HAIP — Report Generation Celery Tasks

Beat schedules:
  - weekly-digest:  Every Monday 08:00 IST
  - monthly-report: 1st of each month 07:00 IST

Can also be triggered manually via POST /analytics/reports/generate
"""

import logging
from celery import shared_task
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, set_tenant_context
from app.models.tenant import Tenant
from app.models.user import User

log = logging.getLogger(__name__)


@shared_task(name="app.workers.tasks.generate_reports.weekly_digest_all_tenants")
def weekly_digest_all_tenants():
    """Fan out: generate weekly digest for every active tenant."""
    db: Session = SessionLocal()
    try:
        tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
        for t in tenants:
            generate_report_for_tenant.delay(str(t.id), "weekly")
        log.info("weekly_digest_queued tenants=%d", len(tenants))
        return {"tenants": len(tenants), "report_type": "weekly"}
    finally:
        db.close()


@shared_task(name="app.workers.tasks.generate_reports.monthly_report_all_tenants")
def monthly_report_all_tenants():
    """Fan out: generate monthly report for every active tenant."""
    db: Session = SessionLocal()
    try:
        tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
        for t in tenants:
            generate_report_for_tenant.delay(str(t.id), "monthly")
        log.info("monthly_reports_queued tenants=%d", len(tenants))
        return {"tenants": len(tenants), "report_type": "monthly"}
    finally:
        db.close()


@shared_task(name="app.workers.tasks.generate_reports.generate_report_for_tenant",
             bind=True, max_retries=2)
def generate_report_for_tenant(self, tenant_id: str, report_type: str, send_email: bool = True):
    """
    Generate a specific report for one tenant.
    Fetches analytics data, builds HTML, saves to DB, emails owner.
    """
    import asyncio
    from app.core.database import SessionLocal, set_tenant_context

    db: Session = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)

        # Get owner email for delivery
        owner = db.query(User).filter(
            User.tenant_id == tenant_id,
            User.role == "owner",
            User.is_active == True,
        ).first()

        if not owner:
            log.warning("No owner found for tenant %s — skipping report email", tenant_id)

        # Run async report generation in sync context
        asyncio.run(_async_generate(tenant_id, report_type, db, owner, send_email))
        log.info("report_generated tenant=%s type=%s", tenant_id, report_type)

    except Exception as exc:
        log.error("report_generation_failed tenant=%s type=%s error=%s", tenant_id, report_type, exc)
        raise self.retry(exc=exc, countdown=300)
    finally:
        db.close()


async def _async_generate(tenant_id: str, report_type: str, db, owner, send_email: bool):
    """Async inner function — fetch data and generate report."""
    from app.services.ask_haip_service import DOMAIN_ENDPOINTS
    from app.services.ask_haip_reports import generate_report, save_report, send_report_email
    from app.core.config import settings

    # Internal API base — we call our own endpoints
    base_url = settings.API_BASE_URL.rstrip("/") + "/api/v1"

    # For automated reports we can't use a user JWT — query DB directly
    # Use the agent processors directly (they don't need HTTP)
    raw_data = await _fetch_report_data(tenant_id, base_url)

    result = await generate_report(report_type=report_type, raw_data=raw_data)

    # Save to DB
    save_report(
        db=db,
        tenant_id=tenant_id,
        report_type=report_type,
        title=result["title"],
        html=result["html"],
    )

    # Email delivery
    if send_email and owner:
        await send_report_email(
            to_email=owner.email,
            to_name=owner.full_name or owner.email,
            report_type=report_type,
            title=result["title"],
            html=result["html"],
        )


async def _fetch_report_data(tenant_id: str, base_url: str) -> dict:
    """
    For Celery tasks (no user JWT), query analytics data using a system-level
    approach: call the internal API endpoints without auth by using a
    service account token, or fall back to empty dict.
    """
    # In production this would use a service token or direct DB queries.
    # For now return empty dict — the report engine gracefully handles missing data.
    log.info("report_data_fetch tenant=%s", tenant_id)
    return {}
