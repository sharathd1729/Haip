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
from app.services import call_status_service, inbox_service
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
    "phone": ("call", "Phone calls"),
    "inbound_call": ("call", "Phone calls"),
    "outbound_call": ("call", "Phone calls"),
    "website": ("website", "Website"),
    "google": ("website", "Website"),
}


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _ist_day(dt: datetime) -> date:
    return _aware(dt).astimezone(IST).date()


# ── Needs you now ─────────────────────────────────────────────────────────────

def needs_you_now(db: Session, tenant, scope_user_id: Optional[str]) -> dict:
    """The four dashboard cards. Thin wrapper over work_queue_service so the
    cards, My day and the Calls call-back tab can never disagree -- this used
    to be its own set of queries, which is exactly how they drifted apart."""
    from app.services import work_queue_service

    res = work_queue_service.counts(db, tenant, scope_user_id)
    c, oldest = res["counts"], res["oldest"]
    return {
        "waiting_reply": c["reply"], "waiting_oldest_at": oldest["reply"],
        "missed_not_called_back": c["callback"], "missed_oldest_at": oldest["callback"],
        "phone_not_called": c["call_new"],
        "followups_overdue": c["followup"], "followups_oldest_due": oldest["followup"],
        "unassigned": c["unassigned"],
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

    inq_q = db.query(Inquiry.created_at).filter(
        Inquiry.tenant_id == tid, Inquiry.created_at >= start, Inquiry.created_at <= end,
        Inquiry.qualification_status != "unqualified",
    )
    if scope_user_id:
        inq_q = inq_q.filter(Inquiry.assigned_to == scope_user_id)
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
        Inquiry.tenant_id == tid, Inquiry.created_at >= range_start, Inquiry.created_at <= range_end,
        Inquiry.qualification_status != "unqualified",
    )
    if scope_user_id:
        q = q.filter(Inquiry.assigned_to == scope_user_id)
    grouped: dict[str, list] = {}
    for source, n in q.group_by(Inquiry.source).all():
        raw = str(getattr(source, "value", source) or "other")
        key, label = _SOURCE_GROUPS.get(raw, ("other", "Other"))
        if key not in grouped:
            grouped[key] = [label, 0]
        grouped[key][1] += n
    total = sum(v[1] for v in grouped.values()) or 1
    out = [{"key": k, "label": v[0], "count": v[1], "pct": round(100 * v[1] / total)} for k, v in grouped.items()]
    return sorted(out, key=lambda r: -r["count"])
