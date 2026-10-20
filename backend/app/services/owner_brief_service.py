"""The owner's daily brief (option C, owner pick 21 Oct 2026): a few plain sentences about the day, three things to do, links.

Replaces the old daily owner report's own numbers (daily_report_service): every figure here comes from the SAME definitions as
the Owner dashboard and My day, so the email and the app never disagree.

  New leads       lead_metrics.count_new_leads    people whose phone number was captured (not enquiries, not DMs)
  Qualified       lead_metrics.count_qualified_new  of those, with a non-spam enquiry in a valid stage (as of now)
  Booked          kpi_metrics.booked_value        bookings made in the period, rental + add-ons (D-24); money only for
                                                  readers with bookings.read
  Top source      lead_metrics.by_first_touch     first-touch channel of the new leads
  Missed calls    inbound, not answered (call_status_service), on the workspace's CURRENT IVR provider only
  Lost            leads moved to the closed-lost stage in the period, with the most common reason
  To-dos          work_queue_service.build(): the "Call now" lane (lead_priority), callbacks and quiet leads

Each count is compared with the average of the 7 days before. The sentences are written from the numbers by rules (no LLM):
nothing is invented and nothing is paid for. Periods are IST calendar days: the morning brief covers yesterday, the evening one
today so far. ``worth_sending`` is False on a day with nothing to say and nothing to do.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.call import Call
from app.models.inquiry import Inquiry
from app.models.inquiry_360 import InquiryStageLog
from app.models.pipeline_stage import PipelineStage
from app.models.tenant import Tenant
from app.services import call_status_service, kpi_metrics, lead_metrics, work_queue_service
from app.services.date_presets import IST, ist_range_to_utc
from app.services.wa_booking_messages import inr

BASELINE_DAYS = 7
TODO_LIMIT = 3
LOST_REASON_LABEL = {"wrong_dates": "dates", "weather_concern": "the weather", "budget_mismatch": "budget",
                     "couldnt_decide": "indecision", "chose_competitor": "a competitor", "no_response": "no response",
                     "capacity": "group size", "other": "other reasons"}


def _plural(n: int, one: str, many: Optional[str] = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _range(d_from: date, d_to: date) -> tuple[datetime, datetime]:
    _, _, start, end = ist_range_to_utc(d_from.isoformat(), d_to.isoformat())
    return start, end


def _missed_calls(db: Session, tenant: Tenant, start: datetime, end: datetime) -> int:
    q = db.query(func.count(Call.id)).filter(Call.tenant_id == tenant.id, Call.created_at >= start, Call.created_at <= end,
                                             call_status_service.missed_call_sql_filter())
    if tenant.ivr_provider:                     # history from a disconnected provider must not count (catalogue: calls)
        q = q.filter(Call.ivr_provider == tenant.ivr_provider)
    return int(q.scalar() or 0)


def _lost(db: Session, tid: str, start: datetime, end: datetime) -> tuple[int, Optional[str]]:
    lost_keys = [k for (k,) in db.query(PipelineStage.key).filter(PipelineStage.tenant_id == tid,
                                                                   PipelineStage.is_closed_lost.is_(True)).all()]
    if not lost_keys:
        return 0, None
    ids = {i for (i,) in db.query(InquiryStageLog.inquiry_id).filter(
        InquiryStageLog.tenant_id == tid, InquiryStageLog.to_stage.in_(lost_keys),
        InquiryStageLog.changed_at >= start, InquiryStageLog.changed_at <= end).all()}
    if not ids:
        return 0, None
    reasons = Counter(getattr(r, "value", r) for (r,) in db.query(Inquiry.lost_reason).filter(
        Inquiry.tenant_id == tid, Inquiry.id.in_(list(ids))).all() if r)
    top = reasons.most_common(1)[0][0] if reasons else None
    return len(ids), LOST_REASON_LABEL.get(top, top) if top else None


def _numbers(db: Session, tenant: Tenant, start: datetime, end: datetime) -> dict:
    tid = tenant.id
    booked = kpi_metrics.booked_value(db, tid, start, end)
    lost, lost_reason = _lost(db, tid, start, end)
    return {"leads": lead_metrics.count_new_leads(db, tid, start, end),
            "qualified": lead_metrics.count_qualified_new(db, tid, start, end),
            "bookings": booked["count"], "booked_value": booked["total"],
            "missed_calls": _missed_calls(db, tenant, start, end),
            "lost": lost, "lost_reason": lost_reason}


def _compare(n: float, avg: Optional[float]) -> str:
    if avg is None:
        return ""
    if abs(n - avg) < 1:
        return "about your usual"
    return f"{'more' if n > avg else 'fewer'} than your daily average of {avg:.0f}" if avg >= 1 else ""


def _sentences(nums: dict, base: dict, period: str, top_source: Optional[str], money: bool) -> list[str]:
    out = []
    leads = nums["leads"]
    if leads:
        cmp = _compare(leads, base.get("leads"))
        s = f"{period} brought {_plural(leads, 'new lead')} (people who shared a phone number)"
        s += f", {cmp}" if cmp else ""
        s += f", mostly from {top_source}." if top_source else "."
        out.append(s)
    else:
        out.append(f"No new leads {period.lower()}.")
    if nums["bookings"]:
        value = f" for {inr(nums['booked_value'])}" if money and nums["booked_value"] else ""
        out.append(f"{_plural(nums['bookings'], 'trip')} booked{value}.")
    if nums["missed_calls"]:
        out.append(f"{_plural(nums['missed_calls'], 'call')} went unanswered.")
    if nums["lost"]:
        why = f", mostly over {nums['lost_reason']}" if nums["lost_reason"] else ""
        out.append(f"{_plural(nums['lost'], 'lead')} marked lost{why}.")
    return out


def _todos(queue: dict, app_url: str) -> list[dict]:
    """The best few people to call now (My day's "Call now" lane), then what remains, as counts."""
    items = [i for i in queue["items"] if i.get("kind") != "clash"]
    now = [i for i in items if i.get("lane") == "now"]
    todos = []
    for i in now[:TODO_LIMIT]:
        why = ", ".join((i.get("reasons") or [])[:2]) or i.get("detail") or ""
        verb = "Call back" if i["kind"] == "callback" or "Asked for a call back" in (i.get("reasons") or []) else "Call"
        todos.append({"text": f"{verb} {i['title']}" + (f": {why.lower()}" if why else ""),
                      "url": f"{app_url}{i['href']}" if i.get("href", "").startswith("/") else f"{app_url}/dashboard/my-day"})
    rest = len(now) - len(todos)
    if rest > 0:
        todos.append({"text": f"{_plural(rest, 'more person', 'more people')} to call now", "url": f"{app_url}/dashboard/my-day"})
    quiet = sum(1 for i in items if i.get("kind") == "no_reply")
    if quiet:
        todos.append({"text": f"Follow up {_plural(quiet, 'lead')} who went quiet after our message",
                      "url": f"{app_url}/dashboard/my-day?kind=no_reply"})
    return todos


def build(db: Session, tenant: Tenant, *, kind: str = "morning", app_url: str, now: Optional[datetime] = None,
          money: bool = True) -> dict:
    now_ist = (now or datetime.now(IST)).astimezone(IST)
    day = now_ist.date() - timedelta(days=1) if kind == "morning" else now_ist.date()
    period = "Yesterday" if kind == "morning" else "Today so far"
    start, end = _range(day, day)
    nums = _numbers(db, tenant, start, end)
    b_start, b_end = _range(day - timedelta(days=BASELINE_DAYS), day - timedelta(days=1))
    b_leads = lead_metrics.count_new_leads(db, tenant.id, b_start, b_end)
    base = {"leads": b_leads / BASELINE_DAYS}
    sources = lead_metrics.by_first_touch(db, tenant.id, start, end, with_bookings=False)
    top = sources[0] if sources else None
    top_source = top["label"] if top and nums["leads"] >= 2 and top["key"] != "unknown" and top["leads"] * 2 >= nums["leads"] else None
    queue = work_queue_service.build(db, tenant, None)
    todos = _todos(queue, app_url)
    sentences = _sentences(nums, base, period, top_source, money)
    activity = nums["leads"] or nums["bookings"] or nums["missed_calls"] or nums["lost"]
    return {
        "kind": kind, "day": day.isoformat(), "day_label": f"{day:%a}, {day.day} {day:%b}", "period": period,
        "numbers": nums, "baseline": base, "top_source": top_source, "sentences": sentences, "todos": todos,
        "worth_sending": bool(activity or todos), "money": money,
        "my_day_url": f"{app_url}/dashboard/my-day", "dashboard_url": f"{app_url}/dashboard",
    }
