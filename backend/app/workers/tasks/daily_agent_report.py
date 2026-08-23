"""Per-agent end-of-day report email -- each sales agent's own leads,
calls, and a short performance narrative for the day, mirroring
daily_owner_report.py's exact shape (fan-out task -> per-recipient send).

Recipients: active, non-owner/manager users with an email on file. Owners
and managers already get the team-wide picture in the owner report's
per-agent section (daily_report_service.get_agent_breakdown); this is the
individual counterpart, sent to the agent themselves.
"""

import asyncio

import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context
from app.core.config import settings
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import daily_report_service
from app.services.daily_report_email import render_agent_report_html, render_agent_report_subject

log = structlog.get_logger()

DASHBOARD_URL = "https://www.genhaip.com/dashboard"


def _recipients(db, tenant_id: str) -> list[User]:
    return (
        db.query(User)
        .filter(
            User.tenant_id == tenant_id,
            User.role.notin_([UserRole.OWNER, UserRole.MANAGER]),
            User.is_active.is_(True),
            User.is_deleted.is_(False),
        )
        .all()
    )


@shared_task(name="reports.send_daily_agent_report", bind=True, max_retries=2)
def send_daily_agent_report(self, tenant_id: str, agent_id: str, day: str | None = None, to_email: str | None = None):
    """Build and email one agent's daily performance report.

    `to_email` overrides the recipient -- manual test-send, mirrors
    daily_owner_report.py's send_daily_owner_report.
    """
    from app.services.email_service import _send

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            log.warning("daily_agent_report_tenant_missing", tenant_id=tenant_id)
            return {"tenant_id": tenant_id, "agent_id": agent_id, "status": "no_tenant"}

        block = daily_report_service.build_agent_daily_report(db, tenant_id, agent_id, day=day)
        if not block:
            log.info("daily_agent_report_no_data", tenant_id=tenant_id, agent_id=agent_id)
            return {"tenant_id": tenant_id, "agent_id": agent_id, "status": "no_data"}

        html = render_agent_report_html(block, tenant_name=tenant.name, dashboard_url=DASHBOARD_URL)
        subject = render_agent_report_subject(block, tenant.name)

        if to_email:
            addr = to_email
        else:
            agent = db.query(User).filter_by(id=agent_id, tenant_id=tenant_id).first()
            addr = agent.email if agent else None

        if not addr:
            log.warning("daily_agent_report_no_email", tenant_id=tenant_id, agent_id=agent_id)
            return {"tenant_id": tenant_id, "agent_id": agent_id, "status": "no_email"}

        ok = asyncio.run(_send(addr, subject, html))

        log.info(
            "daily_agent_report_sent", tenant_id=tenant_id, agent_id=agent_id,
            date=block["date"], sent=ok,
        )
        return {"tenant_id": tenant_id, "agent_id": agent_id, "date": block["date"], "sent": ok}
    finally:
        db.close()


@shared_task(name="reports.daily_agent_report_all_tenants")
def daily_agent_report_all_tenants():
    """Fan out to every active tenant's every eligible agent. Beat fires
    this once a day, after the owner's evening report."""
    if not settings.RESEND_API_KEY:
        log.warning("daily_agent_report_skipped_no_email_key")
        return {"agents_queued": 0, "reason": "no_email_key"}

    db = SessionLocal()
    try:
        tenant_ids = [t.id for t in db.query(Tenant).filter(Tenant.is_active.is_(True)).all()]
        queued = 0
        for tid in tenant_ids:
            for agent in _recipients(db, tid):
                if agent.email:
                    send_daily_agent_report.delay(tid, agent.id)
                    queued += 1
    finally:
        db.close()

    log.info("daily_agent_report_queued", agents=queued)
    return {"agents_queued": queued}
