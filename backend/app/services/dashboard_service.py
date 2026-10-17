"""Owner Daily dashboard pieces added on top of GET /dashboard/overview:

- needs_you_now: the four live queues the dashboard leads with, each the
  same definition its own screen uses (Inbox "Needs reply", Calls "Call
  back", Leads "Shared a phone", overdue tasks), so the counts match.
- daily_series: per-day numbers for the KPI sparklines and the revenue
  chart, plus the previous period's revenue for comparison.
- lead_sources: where the period's leads came from.

All tenant-scoped; an agent's numbers are scoped to themselves the same way
the rest of the overview is (scope_user_id).
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.call import Call, CallDirection
from app.models.conversation import Conversation
from app.models.inquiry import Inquiry
from app.models.property import Stay
from app.models.task import Task
from app.services import call_status_service, inbox_service, kpi_metrics
from app.services.date_presets import IST

# Same windows as the screens these link to.
_CALLBACK_WINDOW = timedelta(days=7)
_MAX_SERIES_DAYS = 62
_MIN_SERIES_DAYS = 7  # a sparkline needs a few points even for "Today"

_SOURCE_GROUPS = {
    "meta_ig": ("instagram", "Instagram"),
    "meta_fb": ("facebook", "Facebook"),
    "wa_direct": ("whatsapp", "WhatsApp"),
    "click_to_wa": ("whatsapp", "WhatsApp"),
    # Calls: "organic_call" is an inbound call that arrived with no ad or campaign behind it (set when HAIP creates the lead
    # from the call). Older call leads keep their recorded source and stay under "Phone calls": they are not re-labelled.
    "organic_call": ("organic_call", "Organic calls"),
    "phone": ("call", "Phone calls"),
    "inbound_call": ("call", "Phone calls"),
    "outbound_call": ("call", "Phone calls"),
    "website": ("website", "Website"),
    "google": ("website", "Website"),
    "web_chat": ("website", "Website"),
    "email": ("email", "Email"),
    "walk_in": ("walk_in", "Walk-in"),
    "referral": ("referral", "Referral & agents"),
    "travel_agent": ("referral", "Referral & agents"),
    "ota_airbnb": ("ota", "OTAs & channel managers"),
    "ota_booking": ("ota", "OTAs & channel managers"),
    "ota_vrbo": ("ota", "OTAs & channel managers"),
    "ota_mmt": ("ota", "OTAs & channel managers"),
    "ota_goibibo": ("ota", "OTAs & channel managers"),
    "channel_manager": ("ota", "OTAs & channel managers"),
}
# A lead with no recorded source is shown as such. It is never guessed into a real channel.
UNKNOWN_SOURCE = ("other", "Not recorded")


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _ist_day(dt: datetime) -> date:
    return _aware(dt).astimezone(IST).date()


# ── Needs you now ─────────────────────────────────────────────────────────────

def needs_you_now(db: Session, tenant, scope_user_id: Optional[str]) -> dict:
    """The dashboard cards. Thin wrapper over work_queue_service so the
    cards, My day and the Calls call-back tab can never disagree -- this used
    to be its own set of queries, which is exactly how they drifted apart."""
    from app.services import work_queue_service

    return needs_you_now_from(work_queue_service.counts(db, tenant, scope_user_id))


def needs_you_now_from(res: dict) -> dict:
    """The same four cards from an already-built work-queue result (``build`` and ``counts`` both carry counts and
    oldest), so a caller that also needs the items does not query the queue twice."""
    c, oldest = res["counts"], res["oldest"]
    return {
        "new_leads": c["new_lead"], "new_leads_oldest_at": oldest["new_lead"],
        "waiting_reply": c["reply"], "waiting_oldest_at": oldest["reply"],
        "missed_not_called_back": c["callback"], "missed_oldest_at": oldest["callback"],
        "followups_overdue": c["followup"], "followups_oldest_due": oldest["followup"],
        "unassigned": res.get("unowned", 0),
        "people": res.get("people", 0),
        "breached": sum(n for s, n in res.get("severity", {}).items() if s != "fresh"),
    }


# ── Daily series ──────────────────────────────────────────────────────────────

def _day_list(d_from: date, d_to: date) -> list[date]:
    if (d_to - d_from).days + 1 < _MIN_SERIES_DAYS:
        d_from = d_to - timedelta(days=_MIN_SERIES_DAYS - 1)
    if (d_to - d_from).days + 1 > _MAX_SERIES_DAYS:
        d_from = d_to - timedelta(days=_MAX_SERIES_DAYS - 1)
    return [d_from + timedelta(days=i) for i in range((d_to - d_from).days + 1)]


def _utc_bounds(days: list[date]) -> tuple[datetime, datetime]:
    start = datetime.combine(days[0], datetime.min.time(), tzinfo=IST).astimezone(timezone.utc)
    end = datetime.combine(days[-1], datetime.max.time(), tzinfo=IST).astimezone(timezone.utc)
    return start, end


def _revenue_by_day(db: Session, tid: str, days: list[date]) -> tuple[dict, dict]:
    rows = db.query(Stay.check_in, Stay.total_amount).filter(
        Stay.tenant_id == tid,
        Stay.status.in_(["confirmed", "checked_in", "checked_out"]),
        Stay.check_in >= days[0], Stay.check_in <= days[-1],
    ).all()
    revenue, bookings = defaultdict(float), defaultdict(int)
    for check_in, amount in rows:
        d = check_in if isinstance(check_in, date) else date.fromisoformat(str(check_in)[:10])
        revenue[d] += float(amount or 0)
        bookings[d] += 1
    return revenue, bookings


def daily_series(db: Session, tenant, scope_user_id: Optional[str], d_from: str, d_to: str) -> dict:
    """Per-IST-day values. Bookings/revenue are bucketed by check-in date,
    the same basis the KPI tile already uses."""
    tid = tenant.id
    days = _day_list(date.fromisoformat(d_from), date.fromisoformat(d_to))
    start, end = _utc_bounds(days)

    # "New leads" is defined once, in kpi_metrics (leads.new).
    inq_q = db.query(Inquiry.created_at).filter(*kpi_metrics.lead_filters(tid, start, end, scope_user_id=scope_user_id))
    leads = defaultdict(int)
    for (created,) in inq_q.all():
        leads[_ist_day(created)] += 1

    call_q = db.query(Call).filter(Call.tenant_id == tid, Call.created_at >= start, Call.created_at <= end)
    if tenant.ivr_provider:
        call_q = call_q.filter(Call.ivr_provider == tenant.ivr_provider)
    if scope_user_id:
        call_q = call_q.filter(Call.agent_id == scope_user_id)
    inbound, answered = defaultdict(int), defaultdict(int)
    for c in call_q.all():
        if c.direction == CallDirection.INBOUND or str(getattr(c.direction, "value", c.direction)) == "inbound":
            d = _ist_day(c.created_at)
            inbound[d] += 1
            if not call_status_service.is_missed_call(c):
                answered[d] += 1

    revenue, bookings = _revenue_by_day(db, tid, days)
    span = len(days)
    prev_days = [d - timedelta(days=span) for d in days]
    prev_revenue, _ = _revenue_by_day(db, tid, prev_days)

    return {
        "days": [d.isoformat() for d in days],
        "leads": [leads[d] for d in days],
        "bookings": [bookings[d] for d in days],
        "revenue": [round(revenue[d], 2) for d in days],
        "prev_revenue": [round(prev_revenue[d], 2) for d in prev_days],
        "calls_answered_pct": [round(100 * answered[d] / inbound[d]) if inbound[d] else None for d in days],
    }


# ── Lead sources ──────────────────────────────────────────────────────────────

def lead_sources(db: Session, tid: str, scope_user_id: Optional[str], range_start: str, range_end: str) -> list[dict]:
    q = db.query(Inquiry.source, func.count(Inquiry.id)).filter(
        *kpi_metrics.lead_filters(tid, range_start, range_end, scope_user_id=scope_user_id)   # leads.new
    )
    grouped: dict[str, list] = {}
    for source, n in q.group_by(Inquiry.source).all():
        raw = str(getattr(source, "value", source) or "other")
        key, label = _SOURCE_GROUPS.get(raw, UNKNOWN_SOURCE)
        if key not in grouped:
            grouped[key] = [label, 0]
        grouped[key][1] += n
    total = sum(v[1] for v in grouped.values()) or 1
    out = [{"key": k, "label": v[0], "count": v[1], "pct": round(100 * v[1] / total)} for k, v in grouped.items()]
    return sorted(out, key=lambda r: -r["count"])


# ── AI insights ───────────────────────────────────────────────────────────────

def top_insights(db: Session, tid: str, limit: int = 4) -> list[dict]:
    """The open AI insights that most deserve a look: most severe first, then newest. Severity is sorted BEFORE the
    cut, so a critical insight can no longer be dropped in favour of an older low one."""
    from app.models.insight import Insight

    rows = db.query(Insight).filter(
        Insight.tenant_id == tid, Insight.is_dismissed == False, Insight.is_auto_resolved == False,  # noqa: E712
    ).order_by(Insight.created_at.desc()).limit(50).all()
    severity = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}
    rows.sort(key=lambda r: severity.get(r.severity, 0), reverse=True)
    return [{"id": r.id, "severity": r.severity, "title": r.title, "body": r.body, "cta_label": r.cta_label, "cta_href": r.cta_href}
            for r in rows[:limit]]
