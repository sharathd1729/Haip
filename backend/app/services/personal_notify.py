"""Phone notifications for the Yaad app (GET /devices/updates, device token).

The Yaad app is a WebView, which cannot receive web push, so its background sync (every 15 minutes) asks this feed and
shows what comes back as Android notifications. Three kinds, each behind the person's switch (services/personal_settings):
  summary  "Summary ready": a call summarised since the app last asked (at most 5, newest first)
  due      "N reminders due today": once a day from 09:00 IST, when open reminders are due today
  day      "Your day at a glance": once a day from 22:00 IST, on a day with calls (same time as the email)
Every item has a stable id; the app keeps the ids it showed, so asking twice never shows one twice.
Personal workspaces only: any other workspace gets an empty list.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.services import personal_ask as ask
from app.services import personal_calls as pc
from app.services import personal_settings as ps

IST = ZoneInfo("Asia/Kolkata")
MAX_SUMMARIES = 5
DUE_HOUR = 9
DAY_HOUR = 22
LOOKBACK_DAYS = 45
FIRST_ASK = timedelta(hours=1)  # a newly linked phone hears only about the last hour, not a backlog


def _aware(v) -> datetime | None:
    if isinstance(v, str):
        try:
            v = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(v, datetime):
        return None
    return v if v.tzinfo else v.replace(tzinfo=UTC)


def updates(db, tenant, user, since: datetime | None, now: datetime | None = None) -> list[dict]:
    from app.models.call import Call

    if not pc.is_personal_tenant(tenant):
        return []
    now = now or datetime.now(UTC)
    since = _aware(since) or now - FIRST_ASK
    local = now.astimezone(IST)
    today = local.date()
    start_of_day = datetime.combine(today, datetime.min.time(), tzinfo=IST).astimezone(UTC)

    calls = (
        db.query(Call)
        .filter(
            Call.tenant_id == tenant.id,
            Call.created_at >= now - timedelta(days=LOOKBACK_DAYS),
            Call.ai_insights.isnot(None),
        )
        .order_by(Call.created_at.desc())
        .all()
    )
    calls = [c for c in calls if pc.memory_of(c)]
    out: list[dict] = []

    if ps.switch_on(user, "notify_summary"):
        fresh = [c for c in calls if (_aware(pc.memory_of(c).get("analysed_at")) or since) > since][:MAX_SUMMARIES]
        contact = ask.contact_namer(db, tenant.id, fresh)
        for c in fresh:
            out.append(
                {
                    "id": f"sum:{c.id}",
                    "title": pc.memory_of(c).get("title") or "Call summary ready",
                    "body": f"Summary ready · {contact(c)}",
                    "path": f"/dashboard/me/calls/{c.id}",
                }
            )

    if ps.switch_on(user, "notify_due") and local.hour >= DUE_HOUR:
        due = [
            a["text"]
            for c in calls
            for a in pc.memory_of(c).get("action_items") or []
            if not a.get("done") and a.get("due") == today.isoformat()
        ]
        if due:
            out.append(
                {
                    "id": f"due:{today.isoformat()}",
                    "title": f"{len(due)} reminder{'' if len(due) == 1 else 's'} due today",
                    "body": " · ".join(due[:2]) + (f" · +{len(due) - 2} more" if len(due) > 2 else ""),
                    "path": "/dashboard/me/reminders",
                }
            )

    if ps.switch_on(user, "notify_day") and local.hour >= DAY_HOUR:
        todays = [c for c in calls if (_aware(c.created_at) or now) >= start_of_day]
        if todays:
            n = len(todays)
            out.append(
                {
                    "id": f"day:{today.isoformat()}",
                    "title": "Your day at a glance",
                    "body": f"{n} call{'' if n == 1 else 's'} today. Tap to see what was decided and what's next.",
                    "path": "/dashboard/me",
                }
            )
    return out
