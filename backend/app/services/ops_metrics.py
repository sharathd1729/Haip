"""How operations are doing: the shared ops metrics (ops gap 10, decisions D-38 .. D-45 in KPI_METRIC_CATALOGUE.md).

ONE place for these numbers; Ops Today's block and the owner brief both read ``build``. Registered in
``kpi_metrics.CANONICAL_METRICS`` under ``ops.*``.

Period = IST calendar days [day_from, day_to]. Ops items count by when they were opened; stays by their check-in date.
A stay is judged on "before check-in" only once its check-in moment (check-in date at the stay's pickup / check-in time,
else 12:00 IST) has passed. Stays left out everywhere: cancelled, the "Unassigned" placeholder unit
(``vehicle_pool.placeholder_ids``) and comp stays (creator barter, ``channel_source == "creator"``, D-38).

Empty means unknown: a metric with nothing to judge is ``None`` ("No data"), never 0 or 100%.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.ops import OpsEscalationEvent, OpsItem
from app.models.ops_files import OpsFile, OpsFileEvent, OpsJob, OpsJobItem
from app.models.ops_fleet import OpsGuestForm
from app.models.property import Property, PropertyAddOn, Stay
from app.models.stay_finance import StayAddOn, StayPayment
from app.services import vehicle_pool
from app.services.date_presets import IST, ist_range_to_utc
from app.services.impact_metrics import guest_turns, percentile
from app.services.ops_escalation_service import GUEST_SOURCES
from app.services.ops_money import EXTRA_KM_ADDON
from app.services.work_queue_service import severity_for

SEVERITIES = ("critical", "high", "normal", "low")
COMP_CHANNELS = ("creator",)
# Paperwork chores the system raises on a schedule: they are reminders, not issues with the stay (D-40).
NOT_ISSUES = ("deposit", "form_c")
# Written by ops_trip_service.refresh / ops_stay_service.refresh when the readiness gate opens or closes.
GATE_GREEN = "Every critical check is green"
GATE_LOST = "A critical check is no longer green"
DEFAULT_ARRIVAL = time(12, 0)
REVIEWS_NOTE = "Post-stay review requests (Ops 3b) are not built yet, so there is no review rate to show."


def _utc(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    return v if v.tzinfo else v.replace(tzinfo=UTC)


def _pct(part: int, whole: int) -> float | None:
    return round(part / whole * 100, 1) if whole else None


def _minutes(values: list[float]) -> dict:
    return {"count": len(values), "median_min": percentile(values, 0.5), "p90_min": percentile(values, 0.9)}


def arrival_at(stay: Stay) -> datetime:
    """The stay's check-in moment (UTC): check-in date at its pickup / check-in time, else 12:00 IST."""
    t = DEFAULT_ARRIVAL
    try:
        if stay.check_in_time:
            hh, mm = stay.check_in_time.split(":")[:2]
            t = time(int(hh), int(mm))
    except (ValueError, TypeError):
        t = DEFAULT_ARRIVAL
    return datetime.combine(stay.check_in, t, tzinfo=IST).astimezone(UTC)


def eligible_stays(db: Session, tenant_id: str, day_from: date, day_to: date) -> list[Stay]:
    """Stays checking in inside the period, minus cancelled, placeholder and comp stays (D-38)."""
    q = db.query(Stay).filter(
        Stay.tenant_id == tenant_id,
        Stay.check_in >= day_from,
        Stay.check_in <= day_to,
        Stay.status != "cancelled",
        func.coalesce(Stay.channel_source, "").notin_(COMP_CHANNELS),
    )
    holders = vehicle_pool.placeholder_ids(db, tenant_id)
    if holders:
        q = q.filter(Stay.property_id.notin_(holders))
    return q.all()


def _items(db: Session, tenant_id: str, start: datetime, end: datetime) -> list[OpsItem]:
    return (
        db.query(OpsItem)
        .filter(
            OpsItem.tenant_id == tenant_id,
            OpsItem.created_at >= start,
            OpsItem.created_at <= end,
            OpsItem.status != "cancelled",
        )
        .all()
    )


def _item_property(item: OpsItem, stay_props: dict[str, str]) -> str | None:
    return item.property_id or (stay_props.get(item.stay_id) if item.stay_id else None)


def acknowledge_times(items: list[OpsItem]) -> dict:
    """``ops.time_to_acknowledge`` (D-39): opened (or released from a quiet-hours / morning hold) -> first Acknowledge."""
    by: dict[str, list[float]] = defaultdict(list)
    waiting = 0
    for i in items:
        if i.acknowledged_at is None:
            waiting += i.status == "open"
            continue
        start = max(_utc(i.created_at), _utc(i.dispatch_after) or _utc(i.created_at))
        by[i.severity].append(max(0.0, (_utc(i.acknowledged_at) - start).total_seconds() / 60))
    every = [v for vs in by.values() for v in vs]
    return {
        "all": _minutes(every),
        "by_severity": {s: _minutes(by.get(s, [])) for s in SEVERITIES},
        "not_acknowledged": waiting,
    }


def resolve_times(db: Session, tenant_id: str, items: list[OpsItem]) -> dict:
    """``ops.time_to_resolve`` (D-39): opened -> fixed. A guest ticket is fixed when the GUEST said yes (the
    ``guest_confirmed`` event, PR #141); one closed without the guest's answer is counted apart, never timed. Other
    items are fixed when a person resolved them."""
    guest_ids = [i.id for i in items if i.source in GUEST_SOURCES and i.guest_id]
    confirmed: dict[str, datetime] = {}
    if guest_ids:
        for item_id, at in (
            db.query(OpsEscalationEvent.item_id, func.min(OpsEscalationEvent.created_at))
            .filter(
                OpsEscalationEvent.tenant_id == tenant_id,
                OpsEscalationEvent.item_id.in_(guest_ids),
                OpsEscalationEvent.event == "guest_confirmed",
            )
            .group_by(OpsEscalationEvent.item_id)
        ):
            confirmed[item_id] = _utc(at)
    by: dict[str, list[float]] = defaultdict(list)
    no_guest_answer = 0
    for i in items:
        if i.id in confirmed:
            done = confirmed[i.id]
        elif i.source in GUEST_SOURCES and i.guest_id:
            no_guest_answer += i.status == "resolved"
            continue
        elif i.status == "resolved" and i.resolved_at is not None:
            done = _utc(i.resolved_at)
        else:
            continue
        by[i.severity].append(max(0.0, (done - _utc(i.created_at)).total_seconds() / 60))
    every = [v for vs in by.values() for v in vs]
    return {
        "all": _minutes(every),
        "by_severity": {s: _minutes(by.get(s, [])) for s in SEVERITIES},
        "closed_without_guest_answer": no_guest_answer,
    }


def _repeats(
    db: Session, tenant_id: str, file_ids: list[str], file_props: dict[str, str], names: dict[str, str]
) -> list:
    """The same checklist item failing on the same unit more than once in the period (red now, or a photo check that
    said "not fine")."""
    if not file_ids:
        return []
    rows = (
        db.query(OpsJob.file_id, OpsJobItem.key, OpsJobItem.label, OpsJobItem.status, OpsJobItem.ai_verdict)
        .join(OpsJobItem, OpsJobItem.job_id == OpsJob.id)
        .filter(OpsJob.tenant_id == tenant_id, OpsJobItem.tenant_id == tenant_id, OpsJob.file_id.in_(file_ids))
        .all()
    )
    seen: Counter = Counter()
    labels: dict[tuple, str] = {}
    for file_id, key, label, status, verdict in rows:
        failed = status == "red" or (isinstance(verdict, dict) and verdict.get("ok") is False)
        prop = file_props.get(file_id)
        if failed and prop:
            seen[(prop, key)] += 1
            labels[(prop, key)] = label
    return [
        {"property_id": p, "property": names.get(p, ""), "key": k, "label": labels[(p, k)], "times": n}
        for (p, k), n in seen.most_common()
        if n >= 2
    ][:10]


def ready_on_time(db: Session, tenant_id: str, judged: list[Stay], files: dict[str, OpsFile]) -> dict[str, bool]:
    """``ops.ready_on_time`` (D-41): per stay with an ops file, was the readiness gate open (its last gate event before
    the check-in moment says green)?"""
    ids = [files[s.id].id for s in judged if s.id in files]
    events: dict[str, list[tuple[datetime, str]]] = defaultdict(list)
    if ids:
        for file_id, at, text in db.query(OpsFileEvent.file_id, OpsFileEvent.at, OpsFileEvent.text).filter(
            OpsFileEvent.tenant_id == tenant_id, OpsFileEvent.file_id.in_(ids), OpsFileEvent.auto.is_(True)
        ):
            if text.startswith(GATE_GREEN) or text.startswith(GATE_LOST):
                events[file_id].append((_utc(at), text))
    out = {}
    for s in judged:
        f = files.get(s.id)
        if f is None:
            continue
        before = sorted(e for e in events[f.id] if e[0] <= arrival_at(s))
        out[s.id] = bool(before) and before[-1][1].startswith(GATE_GREEN)
    return out


def paperwork_done(db: Session, tenant_id: str, judged: list[Stay], files: dict[str, OpsFile]) -> dict[str, bool]:
    """``ops.paperwork_before_arrival`` (D-42): guest form sent AND the booking paid in full (rental + add-ons added by
    then), both before the check-in moment. A booking with nothing to pay is judged on the form alone."""
    stays = [s for s in judged if s.id in files]
    ids = [s.id for s in stays]
    if not ids:
        return {}
    forms = {
        sid: _utc(at)
        for sid, at in db.query(OpsGuestForm.stay_id, OpsGuestForm.submitted_at).filter(
            OpsGuestForm.tenant_id == tenant_id, OpsGuestForm.stay_id.in_(ids), OpsGuestForm.submitted_at.isnot(None)
        )
    }
    addons = (
        db.query(StayAddOn.stay_id, StayAddOn.quantity, StayAddOn.unit_price, StayAddOn.created_at)
        .filter(StayAddOn.tenant_id == tenant_id, StayAddOn.stay_id.in_(ids))
        .all()
    )
    signed = case((StayPayment.kind == "refund", -StayPayment.amount), else_=StayPayment.amount)
    pays = (
        db.query(StayPayment.stay_id, StayPayment.paid_on, signed)
        .filter(StayPayment.tenant_id == tenant_id, StayPayment.stay_id.in_(ids))
        .all()
    )
    out = {}
    for s in stays:
        due = arrival_at(s)
        owed = float(s.total_amount or 0) + sum(
            float(q or 0) * float(p or 0) for sid, q, p, at in addons if sid == s.id and _utc(at) <= due
        )
        paid = sum(float(a or 0) for sid, on, a in pays if sid == s.id and on <= s.check_in)
        form = forms.get(s.id)
        out[s.id] = form is not None and form <= due and paid + 0.5 >= owed
    return out


def addon_revenue(db: Session, tenant_id: str, stays: list[Stay]) -> tuple[bool, dict[str, float | None]]:
    """``ops.addon_revenue_per_stay`` (D-43): add-ons on fully paid bookings (the caravan "Extra distance" line is a
    charge, not an add-on). Not live (no add-on catalogue and no add-on ever sold) = "No data"."""
    live = bool(
        db.query(PropertyAddOn.id).filter(PropertyAddOn.tenant_id == tenant_id).first()
        or db.query(StayAddOn.id).filter(StayAddOn.tenant_id == tenant_id).first()
    )
    if not live or not stays:
        return live, {}
    from app.services.booking_service import financials_for

    money = financials_for(db, tenant_id, stays)
    ids = [s.id for s in stays if money[s.id]["outstanding"] <= 0]
    per: dict[str, float] = defaultdict(float)
    if ids:
        for sid, total in (
            db.query(StayAddOn.stay_id, func.sum(StayAddOn.quantity * StayAddOn.unit_price))
            .filter(StayAddOn.tenant_id == tenant_id, StayAddOn.stay_id.in_(ids), StayAddOn.name != EXTRA_KM_ADDON)
            .group_by(StayAddOn.stay_id)
        ):
            per[sid] = float(total or 0)
    return live, {s.id: per.get(s.id, 0.0) for s in stays}


def in_stay_replies(
    db: Session, tenant_id: str, stays: list[Stay], start: datetime, end: datetime, now: datetime
) -> dict[str, list[bool]]:
    """``ops.in_stay_reply`` (D-44): guest turns (``replies.first_response``'s rule) written while the guest's stay was
    on (check-in day to check-out day, IST), answered while the work queue's ``reply`` SLA was still fresh
    (``severity_for``; an AI reply counts, as it does for the queue). Per stay: one bool per turn."""
    by_guest: dict[str, list[Stay]] = defaultdict(list)
    for s in stays:
        if s.check_in <= now.astimezone(IST).date():
            by_guest[s.guest_id].append(s)
    if not by_guest:
        return {}
    turns = guest_turns(db, tenant_id, start, end, now=now)["turns"]
    convs = {c for c in (t.get("conversation_id") for t in turns) if c}
    guest_of = (
        dict(
            db.query(Conversation.id, Conversation.guest_id)
            .filter(Conversation.tenant_id == tenant_id, Conversation.id.in_(list(convs)))
            .all()
        )
        if convs
        else {}
    )
    out: dict[str, list[bool]] = defaultdict(list)
    for t in turns:
        day = t["at"].astimezone(IST).date()
        stay = next(
            (s for s in by_guest.get(guest_of.get(t.get("conversation_id")), []) if s.check_in <= day <= s.check_out),
            None,
        )
        if stay is None:
            continue
        answered = t["at"] + timedelta(seconds=t["reply_seconds"]) if t["reply_seconds"] is not None else now
        out[stay.id].append(t["reply_seconds"] is not None and severity_for("reply", t["at"], answered) == "fresh")
    return out


def build(db: Session, tenant_id: str, day_from: date, day_to: date, *, now: datetime | None = None) -> dict:
    """Every ops metric for the period, overall and per property (the Unassigned holder never listed)."""
    now = _utc(now) or datetime.now(UTC)
    _, _, start, end = ist_range_to_utc(day_from.isoformat(), day_to.isoformat())
    stays = eligible_stays(db, tenant_id, day_from, day_to)
    judged = [s for s in stays if arrival_at(s) <= now]
    stay_props = {s.id: s.property_id for s in stays}
    files = (
        {
            f.stay_id: f
            for f in db.query(OpsFile).filter(
                OpsFile.tenant_id == tenant_id, OpsFile.stay_id.in_([s.id for s in stays])
            )
        }
        if stays
        else {}
    )
    holders = set(vehicle_pool.placeholder_ids(db, tenant_id))
    names = {p: n for p, n in db.query(Property.id, Property.name).filter(Property.tenant_id == tenant_id)}

    raw = _items(db, tenant_id, start, end)
    other = {i.stay_id for i in raw if i.stay_id and i.stay_id not in stay_props}
    item_props = {
        **stay_props,
        **(
            dict(
                db.query(Stay.id, Stay.property_id).filter(Stay.tenant_id == tenant_id, Stay.id.in_(list(other))).all()
            )
            if other
            else {}
        ),
    }
    items = [i for i in raw if _item_property(i, item_props) not in holders]
    issues = [i for i in items if (i.category or "") not in NOT_ISSUES and _item_property(i, item_props)]
    ready = ready_on_time(db, tenant_id, judged, files)
    paper = paperwork_done(db, tenant_id, judged, files)
    live, addons = addon_revenue(db, tenant_id, stays)
    replies = in_stay_replies(db, tenant_id, stays, start, end, now)
    file_props = {f.id: stay_props[sid] for sid, f in files.items()}
    acks = acknowledge_times(items)

    def per_10(n_issues: int, n_stays: int) -> float | None:
        return round(n_issues / n_stays * 10, 1) if n_stays else None

    def reply_block(stay_ids) -> dict:
        flat = [ok for sid in stay_ids for ok in replies.get(sid, [])]
        return {"turns": len(flat), "on_time": sum(flat), "pct": _pct(sum(flat), len(flat))}

    props: dict[str, dict] = {}
    for pid in sorted(
        {s.property_id for s in stays} | {_item_property(i, item_props) for i in issues}, key=lambda p: names.get(p, "")
    ):
        mine = [s for s in stays if s.property_id == pid]
        p_issues = [i for i in issues if _item_property(i, item_props) == pid]
        r = [ready[s.id] for s in mine if s.id in ready]
        pw = [paper[s.id] for s in mine if s.id in paper]
        props[pid] = {
            "property_id": pid,
            "name": names.get(pid, ""),
            "stays": len(mine),
            "issues": len(p_issues),
            "issues_per_10_stays": per_10(len(p_issues), len(mine)),
            "ack_median_min": acknowledge_times(p_issues)["all"]["median_min"],
            "ready_on_time_pct": _pct(sum(r), len(r)),
            "paperwork_pct": _pct(sum(pw), len(pw)),
            "addon_per_stay": round(sum(addons[s.id] for s in mine) / len(mine), 2) if live and mine else None,
            "in_stay_reply_pct": reply_block([s.id for s in mine])["pct"],
        }
    days = (day_to - day_from).days + 1
    return {
        "period": {
            "from": day_from.isoformat(),
            "to": day_to.isoformat(),
            "days": days,
            "label": f"Last {days} days"
            if day_to == now.astimezone(IST).date()
            else f"{day_from:%d %b} - {day_to:%d %b}",
            "timezone": "IST",
        },
        "time_to_acknowledge": acks,
        "time_to_resolve": resolve_times(db, tenant_id, items),
        "issues": {
            "issues": len(issues),
            "stays": len(stays),
            "per_10_stays": per_10(len(issues), len(stays)),
            "repeats": _repeats(db, tenant_id, list(file_props), file_props, names),
        },
        "ready_on_time": {
            "judged": len(ready),
            "on_time": sum(ready.values()),
            "pct": _pct(sum(ready.values()), len(ready)),
        },
        "paperwork_before_arrival": {
            "judged": len(paper),
            "complete": sum(paper.values()),
            "pct": _pct(sum(paper.values()), len(paper)),
        },
        "addon_revenue": {
            "live": live,
            "stays": len(stays) if live else 0,
            "total": round(sum(addons.values()), 2) if live and stays else None,
            "per_stay": round(sum(addons.values()) / len(stays), 2) if live and stays else None,
        },
        "reviews": {"available": False, "note": REVIEWS_NOTE},
        "in_stay_replies": reply_block([s.id for s in stays]),
        "by_property": list(props.values()),
    }


def last_days(db: Session, tenant_id: str, days: int = 30, *, now: datetime | None = None) -> dict:
    """``build`` for the last ``days`` IST days, today included."""
    today = (_utc(now) or datetime.now(UTC)).astimezone(IST).date()
    return build(db, tenant_id, today - timedelta(days=days - 1), today, now=now)
