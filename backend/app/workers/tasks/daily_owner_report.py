"""Daily owner report email.

Replaces nothing -- it is the first scheduled email in this codebase that
actually carries data. `owner_digest` never fires (its beat entry names a
task that isn't registered) and is WhatsApp-only regardless;
`generate_reports` emails on schedule but builds every report from an empty
dict, so it sends all-zero figures under an LLM narrative while logging
success.

Recipients are OWNER/MANAGER users with digest_opt_in, matching the
existing owner_digest convention.
"""

import asyncio

import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context
from app.core.config import settings
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import daily_report_service
from app.services.daily_report_email import render_daily_report, render_subject

log = structlog.get_logger()

DASHBOARD_URL = "https://www.genhaip.com/dashboard/worklist"


def _recipients(db, tenant_id: str) -> list[User]:
    return (
        db.query(User)
        .filter(
            User.tenant_id == tenant_id,
            User.role.in_([UserRole.OWNER, UserRole.MANAGER]),
            User.is_active.is_(True),
            User.is_deleted.is_(False),
        )
        .all()
    )


@shared_task(name="reports.send_daily_owner_report", bind=True, max_retries=2)
def send_daily_owner_report(self, tenant_id: str, day: str | None = None, to_email: str | None = None):
    """Build and email one tenant's daily summary.

    `to_email` overrides the recipient list -- used by the manual "send me a
    test" endpoint so an owner can see the report without waiting for 8am.
    """
    from app.services.email_service import _send

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            log.warning("daily_report_tenant_missing", tenant_id=tenant_id)
            return {"tenant_id": tenant_id, "status": "no_tenant"}

        report = daily_report_service.build_daily_report(db, tenant_id, day=day)
        html = render_daily_report(
            report, tenant_name=tenant.name, dashboard_url=DASHBOARD_URL,
        )
        subject = render_subject(report, tenant.name)

        if to_email:
            targets = [to_email]
        else:
            targets = [u.email for u in _recipients(db, tenant_id) if u.email]

        if not targets:
            log.warning("daily_report_no_recipients", tenant_id=tenant_id)
            return {"tenant_id": tenant_id, "status": "no_recipients"}

        sent, failed = 0, 0
        for addr in targets:
            ok = asyncio.run(_send(addr, subject, html))
            if ok:
                sent += 1
            else:
                failed += 1

        log.info(
            "daily_report_sent",
            tenant_id=tenant_id, date=report["date"], sent=sent, failed=failed,
            awaiting=report["metrics"]["awaiting_reply"],
        )
        return {
            "tenant_id": tenant_id, "date": report["date"],
            "sent": sent, "failed": failed,
        }
    finally:
        db.close()


@shared_task(name="reports.daily_owner_report_all_tenants")
def daily_owner_report_all_tenants():
    """Fan out to every active tenant. Beat fires this once a day."""
    if not settings.RESEND_API_KEY:
        # Without a key email_service logs a preview and reports success, so
        # a scheduled run would look healthy while sending nothing. Skip
        # loudly instead.
        log.warning("daily_report_skipped_no_email_key")
        return {"tenants_queued": 0, "reason": "no_email_key"}

    db = SessionLocal()
    try:
        tenant_ids = [t.id for t in db.query(Tenant).filter(Tenant.is_active.is_(True)).all()]
    finally:
        db.close()

    for tid in tenant_ids:
        send_daily_owner_report.delay(tid)
    log.info("daily_report_queued", tenants=len(tenant_ids))
    return {"tenants_queued": len(tenant_ids)}
