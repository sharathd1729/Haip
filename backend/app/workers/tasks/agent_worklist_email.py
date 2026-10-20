"""Per-agent worklist reminder email -- morning/afternoon/evening nudge for
leads still pending this agent's action (unanswered messages, missed calls,
new leads nobody contacted, guests who went quiet, follow-ups due).

Distinct from daily_agent_report.py (an end-of-day performance summary, sent
once): this is a standing-backlog reminder, sent three times a day, built on
work_queue_service.build() -- the ONE source behind My day (CLAUDE.md: never a
parallel "what to do now" query) -- keeping only the items this agent owns.
Skips the send entirely when the agent has nothing pending, so nobody gets
three "all clear" emails a day.
"""

import asyncio

import structlog
from celery import shared_task

from app.core.database import SessionLocal, set_tenant_context
from app.core.config import settings
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import phone_decline_detector
from app.services.agent_worklist_email import QUEUE_SECTIONS, queue_rows, render_agent_worklist_html, render_agent_worklist_subject

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

        # The agent's own items from the work queue (My day): the same kinds, severities and "who already contacted
        # them" rule as the app, so the email never disagrees with My day. Only items this agent OWNS: unowned leads
        # go to the whole team (team alerts, owner report), not into one person's reminder.
        from app.services import work_queue_service
        items = [i for i in work_queue_service.build(db, tenant, agent_id)["items"] if i.get("owner_id") == agent_id]
        worklist = {kind: queue_rows([i for i in items if i["kind"] == kind]) for kind in QUEUE_SECTIONS}
        worklist.update({
            # Phone-decline alert plan: rendered as its own section
            # (agent_worklist_email.py's _phone_declines_html), not folded
            # into overdue_followups even though it's the same Task model --
            # these read differently and deserve their own count/heading.
            "phone_declines": phone_decline_detector.open_tasks(db, tenant_id, agent_id=agent_id),
        })
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
