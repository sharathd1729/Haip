"""The HAIP Executive's written duties (workspace redesign Phase 3): the five things it does, when, whether each is on for
this workspace, and the last time it did it where that is recorded. Reads only; every duty is the existing machinery:

  morning_brief   daily_owner_report.py / owner_brief_service (08:00 brief, 19:00 check, email; per person
                  notification_prefs.morning_brief_email, default on). Sends are not recorded, so no "last".
  watch_list      chief detectors (services/chief/findings.py): urgent every 5 minutes, full pass 06:30 IST; on with
                  brand_config.chief.enabled. Last = newest finding check.
  proposals       chief plans waiting for a yes (services/chief/approvals.py); nothing runs without a tap.
  weekly_review   the analyst's weekly brief (analyst settings weekly, default Monday 08:30 IST).
  explains        every finding and plan carries its reason and evidence; each finished fix is checked 14 days on
                  (services/chief/outcomes.py).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def duties(db: Session, tenant, user) -> list[dict]:
    from app.models.chief import ChiefProposal
    from app.models.insight import Insight
    from app.services.analyst import reports
    from app.services.analyst import settings as analyst_settings
    from app.services.chief import catalogue
    from app.services.chief import settings as chief_settings

    chief_on = chief_settings.get(tenant).enabled
    analyst = analyst_settings.get(tenant)
    brief_on = (user.notification_prefs or {}).get("morning_brief_email", True) is not False
    last_check = (
        db.query(func.max(Insight.last_seen_at))
        .filter(Insight.tenant_id == tenant.id, Insight.category_code.in_(list(catalogue.BY_CODE)))
        .scalar()
        if catalogue.BY_CODE
        else None
    )
    waiting = (
        db.query(ChiefProposal)
        .filter(ChiefProposal.tenant_id == tenant.id, ChiefProposal.status == "awaiting_approval")
        .count()
    )
    newest_plan = db.query(func.max(ChiefProposal.created_at)).filter(ChiefProposal.tenant_id == tenant.id).scalar()
    weekly = reports.list_reports(db, tenant.id, "weekly_brief", 1)
    checked = (
        db.query(ChiefProposal)
        .filter(
            ChiefProposal.tenant_id == tenant.id,
            ChiefProposal.outcome.isnot(None),
            ChiefProposal.updated_at >= datetime.now(UTC) - timedelta(days=30),
        )
        .count()
    )
    return [
        {
            "key": "morning_brief",
            "title": "Morning brief",
            "what": "Yesterday in numbers, today's arrivals and what's at risk, by email. An evening check follows at 7 pm.",
            "when": "Every day, 8:00 am",
            "on": brief_on,
            "on_note": "your email" if brief_on else "switched off for you",
            "last": None,
            "href": "/dashboard/settings?tab=notifications",
        },
        {
            "key": "watch_list",
            "title": "Watch list",
            "what": "Leads not contacted, chats waiting, quotes about to expire, balances due before check-in, ID forms missing, "
            "low reviews, campaign cost spikes, a channel or integration down.",
            "when": "Every 5 minutes, full pass at 6:30 am",
            "on": chief_on,
            "on_note": None if chief_on else "the Executive is off",
            "last": _iso(last_check),
            "href": "/dashboard/analyst",
        },
        {
            "key": "proposals",
            "title": "Proposals to approve",
            "what": "Plans to fix what it finds: send a reminder, reassign a lead, move a stage. Nothing runs without your tap.",
            "when": "As it finds something",
            "on": chief_on,
            "on_note": f"{waiting} waiting for you" if chief_on else "the Executive is off",
            "last": _iso(newest_plan),
            "count": waiting,
            "href": "/dashboard/analyst?tab=changes",
        },
        {
            "key": "weekly_review",
            "title": "Weekly review",
            "what": "Wins, losses, what changed and three suggestions for the week ahead.",
            "when": f"Mondays, {analyst.weekly.time}",
            "on": bool(analyst.enabled and analyst.weekly.on),
            "on_note": None if analyst.enabled else "the analyst is off",
            "last": weekly[0]["created_at"] if weekly else None,
            "href": "/dashboard/analyst?tab=brief",
        },
        {
            "key": "explains",
            "title": "Explains itself",
            "what": "Every alert and plan says why, with the records behind it; each finished fix is checked again 14 days later.",
            "when": "With every finding and plan",
            "on": chief_on,
            "on_note": None,
            "last": None,
            "count": checked,
            "href": "/dashboard/analyst?tab=history",
        },
    ]
