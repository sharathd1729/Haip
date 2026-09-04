"""Per-agent worklist reminder email -- morning/afternoon/evening nudge for
leads still pending this agent's action (unanswered messages, missed calls,
overdue follow-ups, unactioned shared contact details, new DMs).

Distinct from daily_agent_report.py (an end-of-day performance summary, sent
once): this is a standing-backlog reminder, sent three times a day, built
directly on worklist_service.build_worklist() -- the same data the agent's
own /dashboard/worklist page shows, not a new query. Skips the send entirely
when the agent has nothing pending, so nobody gets three "all clear" emails
a day.
"""

import asyncio

import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context
from app.core.config import settings
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import worklist_service
from app.services.agent_worklist_email import render_agent_worklist_html, render_agent_worklist_subject

log = structlog.get_logger()

DASHBOARD_URL = "https://www.genhaip.com/dashboard"


def _recipients(db, tenant_id: str) -> list[User]:
    """Same scoping as daily_agent_report.py's _recipients() -- active,
    non-deleted, non-owner/manager users. Owners/managers see the team-wide
    picture elsewhere (owner report, dashboard); this is the individual
    agent's own pending-action list."""
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


@shared_task(name="reports.send_agent_worklist_email", bind=True, max_retries=2)
def send_agent_worklist_email(
    self, tenant_id: str, agent_id: str, time_of_day: str = "morning", to_email: str | None = None,
):
    """Build and email one agent's pending-leads worklist.

    `time_of_day` only changes the email's framing copy (all three sends use
    the exact same "right now" query -- there is no separate morning/
    afternoon/evening dataset). `to_email` overrides the recipient, for a
    manual test-send, mirroring send_daily_agent_report's own override.
    """
    from app.services.email_service import _send

    db = SessionLocal()
    try:
        set_tenant_context(db, tenant_id)
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        if not tenant:
            log.warning("agent_worklist_email_tenant_missing", tenant_id=tenant_id)
            return {"tenant_id": tenant_id, "agent_id": agent_id, "status": "no_tenant"}

        agent = db.query(User).filter_by(id=agent_id, tenant_id=tenant_id).first()
        if not agent:
            log.warning("agent_worklist_email_agent_missing", tenant_id=tenant_id, agent_id=agent_id)
            return {"tenant_id": tenant_id, "agent_id": agent_id, "status": "no_agent"}

        # Built from the two worklist_service queries that actually take a
        # scope_user_id (awaiting_reply, overdue_followups) -- NOT
        # build_worklist() as a whole. Its other three sections (missed
        # calls, shared contact details, new DMs) are tenant-wide by design
        # (meant for the owner's/whole-team's worklist view); reusing them
        # here would show every agent the same tenant-wide data regardless
        # of who it's actually assigned to. See agent_worklist_email.py's
        # module docstring for the full reasoning.
        #
        # hours=None on both: this is a standing-backlog reminder, not a
        # rolling window -- a lead that's been waiting 3 days should still
        # show up, not just leads from "today".
        worklist = {
            "awaiting_reply": worklist_service.awaiting_reply(
                db, tenant_id, scope_user_id=agent_id, since=None, limit=worklist_service.SECTION_LIMIT,
            ),
            "overdue_followups": worklist_service.overdue_followups(
                db, tenant_id, scope_user_id=agent_id, limit=worklist_service.SECTION_LIMIT,
            ),
        }
        worklist["counts"] = {k: len(v) for k, v in worklist.items()}
        total_pending = sum(worklist["counts"].values())
        if total_pending == 0:
            log.info("agent_worklist_email_nothing_pending", tenant_id=tenant_id, agent_id=agent_id)
            return {"tenant_id": tenant_id, "agent_id": agent_id, "status": "nothing_pending"}

        html = render_agent_worklist_html(
            worklist, agent_name=agent.name or agent.email, tenant_name=tenant.name,
            dashboard_url=DASHBOARD_URL, time_of_day=time_of_day,
        )
        subject = render_agent_worklist_subject(worklist, agent.name or agent.email, tenant.name)

        addr = to_email or agent.email
        if not addr:
            log.warning("agent_worklist_email_no_email", tenant_id=tenant_id, agent_id=agent_id)
            return {"tenant_id": tenant_id, "agent_id": agent_id, "status": "no_email"}

        ok = asyncio.run(_send(addr, subject, html))

        log.info(
            "agent_worklist_email_sent", tenant_id=tenant_id, agent_id=agent_id,
            time_of_day=time_of_day, pending=total_pending, sent=ok,
        )
        return {"tenant_id": tenant_id, "agent_id": agent_id, "pending": total_pending, "sent": ok}
    finally:
        db.close()


@shared_task(name="reports.agent_worklist_email_all_tenants")
def agent_worklist_email_all_tenants(time_of_day: str = "morning"):
    """Fan out to every active tenant's every eligible agent. Beat fires
    this three times a day (morning/afternoon/evening IST)."""
    if not settings.RESEND_API_KEY:
        log.warning("agent_worklist_email_skipped_no_email_key")
        return {"agents_queued": 0, "reason": "no_email_key"}

    db = SessionLocal()
    try:
        tenant_ids = [t.id for t in db.query(Tenant).filter(Tenant.is_active.is_(True)).all()]
        queued = 0
        for tid in tenant_ids:
            for agent in _recipients(db, tid):
                if agent.email:
                    send_agent_worklist_email.delay(tid, agent.id, time_of_day)
                    queued += 1
    finally:
        db.close()

    log.info("agent_worklist_email_queued", agents=queued, time_of_day=time_of_day)
    return {"agents_queued": queued, "time_of_day": time_of_day}
