"""Who to work on first: a 0-100 priority score and a lane for every work-queue item (My day option B, owner pick 20 Oct 2026).

The work queue used to sort by how far past its target time an item was, so a lead silent for two days sat above a guest who had
just asked us to call. Sales-wise that is backwards: a fresh, detailed enquiry close to its travel date is the one most likely to
book. The score is a plain rule (no AI, no extra calls), built from what the guest told us and how fresh it is:

  base by kind            missed call 35 · new lead 30 · their message waiting 30 · we wrote last 20 · task 15
                          a "Call me back" task 40 (the guest asked)
  fresh                   < 15 min +20 · < 1 h +12 · < 1 day +5            (people only; tasks: due soon +10)
  travel date             in 0-14 days +15 · 15-45 days +8 · already over -> 10 at most, chase lane
  details                 dates +8 · 6+ guests +8 / 3-5 +4 · route +5 · occasion +5
  quote sent              +10
  cooling off             we wrote last: -4 per silent day (max -20) · 3+ unanswered calls -10
                          no trip details at all and older than a day -10 · task overdue 2+ days -10

Lanes (the three sections of My day):
  now     "Call now"                     a missed call, a guest who asked for a call back, a lead or message under a day old,
                                         or a score of 60+
  today   "Reply or follow up today"     the rest that still has a real chance
  chase   "Chase when free"              gone cold, travel date over, or a score under 30

Within a lane: highest score first, then whoever has waited longest. Severity (the SLA clock behind alerts and reminders) is
NOT changed here: this only decides the order and the lane.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy.orm import Session

LANES = ("now", "today", "chase")
_LANE_RANK = {lane: i for i, lane in enumerate(LANES)}

BASE = {"callback": 35, "new_lead": 30, "reply": 30, "no_reply": 20, "followup": 15}
ASKED_CALLBACK_BASE = 40
NOW_SCORE, CHASE_SCORE = 60, 30
_FAR = datetime.max.replace(tzinfo=timezone.utc)


def _day(value) -> Optional[date]:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def asked_for_callback(title: Optional[str]) -> bool:
    """The task the "Call me back" playbook (P7) makes is titled "Callback requested — <name>"."""
    return (title or "").strip().lower().startswith("callback requested")


def score_item(item, inq, *, now: datetime, today: date, quote_out: bool = False) -> tuple[int, str, list[str]]:
    """(score 0-100, lane, reasons) for one queue item. ``inq`` is its enquiry or None."""
    reasons: list[str] = []
    merged = getattr(item, "tasks", None) or []          # tasks folded into a person row (work_queue_signals)
    asked = (item.kind == "followup" and asked_for_callback(item.title)) or \
        any(asked_for_callback(t.get("title")) for t in merged)
    score = ASKED_CALLBACK_BASE if asked else BASE.get(item.kind, 15)
    if asked:
        reasons.append("Asked for a call back")
    elif item.kind == "callback":
        reasons.append("Called us")
    elif item.kind == "reply":
        reasons.append("Their message is waiting")

    since = item.since
    age = (now - since) if since is not None else None
    if item.kind == "followup":
        if age is not None and age < timedelta(0):
            score += 10                                     # due soon, not late yet
        elif age is not None and age >= timedelta(days=2):
            score -= 10
            reasons.append(f"Overdue {age.days} days")
    elif age is not None:
        if age < timedelta(minutes=15):
            score += 20
        elif age < timedelta(hours=1):
            score += 12
        elif age < timedelta(days=1):
            score += 5

    check_in = _day(getattr(inq, "check_in", None))
    check_out = _day(getattr(inq, "check_out", None)) or check_in
    adults = int(getattr(inq, "adults", None) or 0)
    guests = adults + int(getattr(inq, "children", None) or 0)
    route = (getattr(inq, "route_mentioned", None) or "").strip()
    occasion = (getattr(inq, "occasion", None) or "").strip()
    passed = check_out is not None and check_out < today
    if check_in is not None and not passed:
        days = (check_in - today).days
        if days <= 14:
            score += 15
            reasons.append("Travels today" if days <= 0 else f"Travels in {days} day{'s' if days != 1 else ''}")
        elif days <= 45:
            score += 8
    if check_in is not None:
        score += 8
    if guests >= 6:
        score += 8
    elif guests >= 3:
        score += 4
    if route:
        score += 5
    if occasion:
        score += 5
    if quote_out:
        score += 10
        reasons.append("Quote sent")

    if item.kind == "no_reply" and age is not None:
        silent = max(0, age.days)
        score -= min(20, 4 * silent)
        if silent:
            reasons.append(f"Silent {silent} day{'s' if silent != 1 else ''}")
    if (item.attempts or 0) >= 3:
        score -= 10
        reasons.append(f"{item.attempts} calls unanswered")
    if inq is not None and check_in is None and not guests and not route and age is not None and age > timedelta(days=1) \
            and item.kind != "followup":
        score -= 10
        reasons.append("No trip details")

    score = max(0, min(100, score))
    if passed:
        score = min(score, 10)
        reasons.append("Travel date is over")

    fresh_person = item.kind in ("new_lead", "reply") and age is not None and age < timedelta(days=1)
    if passed or item.severity == "stale" or score < CHASE_SCORE and not (asked or item.kind == "callback" or fresh_person):
        lane = "chase"
    elif asked or item.kind == "callback" or fresh_person or score >= NOW_SCORE:
        lane = "now"
    else:
        lane = "today"
    return score, lane, reasons[:4]


def apply(db: Session, tenant_id: str, items: Iterable, now: datetime, today: date) -> None:
    """Set ``priority``, ``lane`` and ``reasons`` on every person item (calendar clashes keep their own section). Two batched
    queries: the enquiries and which of them have a quote."""
    from app.models.inquiry import Inquiry
    from app.models.inquiry_360 import InquiryQuote

    items = [i for i in items if i.kind != "clash"]
    ids = list({i.inquiry_id for i in items if i.inquiry_id})
    inqs = {q.id: q for q in db.query(Inquiry).filter(Inquiry.tenant_id == tenant_id, Inquiry.id.in_(ids)).all()} if ids else {}
    quoted = {r[0] for r in db.query(InquiryQuote.inquiry_id).filter(
        InquiryQuote.tenant_id == tenant_id, InquiryQuote.inquiry_id.in_(ids)).distinct().all()} if ids else set()
    for item in items:
        inq = inqs.get(item.inquiry_id)
        quote_out = item.inquiry_id in quoted or bool(getattr(inq, "quoted_amount", None))
        item.priority, item.lane, item.reasons = score_item(item, inq, now=now, today=today, quote_out=quote_out)


def sort_key(item, aware) -> tuple:
    """Lane, then highest score, then longest wait. Clashes go last (the page shows them in their own section)."""
    if item.kind == "clash":
        return (len(LANES), 0, aware(item.since) or _FAR)
    return (_LANE_RANK.get(item.lane, 1), -(item.priority or 0), aware(item.since) or _FAR)
