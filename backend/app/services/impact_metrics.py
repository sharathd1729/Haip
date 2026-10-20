"""The measured numbers behind the before / after impact view (docs/analytics/KPI_METRIC_CATALOGUE.md section 14).

Registered in kpi_metrics.CANONICAL_METRICS: ``replies.first_response``, ``replies.after_hours``, ``leads.quoted_cohort``,
``calls.missed_returned``, ``enquiries.lost``. Everything else the view shows is an existing shared metric, reused:
``leads.identified_new`` / ``leads.conversion_cohort`` (lead_metrics), ``enquiries.created`` (lead_metrics.enquiry_counts),
``stays.booked`` and ``payments.collected`` (kpi_metrics).

Rules every function here follows (the same as kpi_metrics): tenant first, explicit period bounds (UTC instants of IST days),
an empty period gives counts of 0 and a statistic of ``None`` (never 0 seconds, never 100%). All of it is plain ORM plus Python,
so it runs the same on SQLite and PostgreSQL.

First reply (``replies.first_response``), the definition in one place:
  * A GUEST TURN starts at a guest message (inbound, WhatsApp or Instagram) when the previous message in that chat was a reply
    from us, or was more than 24 hours earlier, or there is none. Further guest messages before our reply belong to the same turn.
    Group chats mirrored from the personal WhatsApp bridge are not guest turns.
  * A REPLY is the first outbound message after the turn starts that really went out: not an internal note, not a failed,
    rejected, pending or queued send (a scheduled message counts once it is sent). AI auto-replies count, as replies typed on the
    agent's own phone (personal WhatsApp bridge, mirrored read-only) do.
  * Channel = where the guest wrote: ``whatsapp_cloud`` (the Cloud API number), ``personal_whatsapp`` (the bridge) or ``instagram``.
  * Responder = who sent the reply: ``ai`` (sent by the AI on its own), ``staff_ai_draft`` (a person sent an AI draft), ``staff``.
  * A turn younger than 60 minutes is left out (it cannot yet be judged against the 60-minute target). Unanswered turns stay in
    the denominator of "answered within"; the median and p90 are over answered turns only.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import exists, func, or_
from sqlalchemy.orm import Session, aliased

from app.core.tenant_tz import is_within_business_hours
from app.models.call import Call
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.inquiry_360 import InquiryQuote
from app.models.pipeline_stage import PipelineStage
from app.services import kpi_metrics, lead_metrics
from app.services.call_status_service import missed_call_sql_filter
from app.services.date_presets import ist_range_to_utc
from app.services.kpi_metrics import UNQUALIFIED, Bound, as_datetime

CHANNELS = ("whatsapp_cloud", "personal_whatsapp", "instagram")
RESPONDERS = ("ai", "staff_ai_draft", "staff")
TARGET_MINUTES = (5, 15, 60)
TURN_GAP = timedelta(hours=24)
TOO_RECENT = timedelta(minutes=60)
REPLY_LOOKAHEAD = timedelta(days=7)
MESSAGE_CAP = 200_000
_NOT_SENT = {MessageDeliveryState.FAILED, MessageDeliveryState.REJECTED, MessageDeliveryState.PENDING, MessageDeliveryState.QUEUED}

LOST_REASON_LABELS = {"wrong_dates": "Dates did not work", "weather_concern": "Weather concern", "budget_mismatch": "Budget",
                      "couldnt_decide": "Could not decide", "chose_competitor": "Chose someone else", "no_response": "Stopped replying",
                      "capacity": "No vehicle free", "other": "Other", None: "Not recorded"}


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, str):
        return as_datetime(value)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def percentile(values: list[float], q: float) -> Optional[float]:
    """Linear interpolation between closest ranks (PostgreSQL percentile_cont). None for no values."""
    if not values:
        return None
    s = sorted(values)
    pos = (len(s) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (pos - lo), 1)


def _pct(part: int, whole: int) -> Optional[float]:
    return round(part / whole * 100, 1) if whole else None


# ── replies.first_response / replies.after_hours ─────────────────────────────────────────────────────────────

def _channel_of(message) -> str:
    meta = message.channel_metadata or {}
    if isinstance(meta, dict) and meta.get("source") == "personal_bridge":
        return "personal_whatsapp"
    return "instagram" if message.channel == ChannelType.INSTAGRAM else "whatsapp_cloud"


def _is_group(message) -> bool:
    meta = message.channel_metadata or {}
    return isinstance(meta, dict) and meta.get("chat_type") == "group"


def _went_out(message) -> bool:
    if message.delivery_state in _NOT_SENT:
        return False
    return (message.channel_status or "").lower() != "failed"


def _responder(message) -> str:
    if message.sent_autonomously or (message.is_ai_generated and not message.sender_id):
        return "ai"
    return "staff_ai_draft" if message.is_ai_generated else "staff"


def guest_turns(db: Session, tenant_id: str, start: Bound, end: Bound, *, now: Optional[datetime] = None) -> dict:
    """Every guest turn that started in [start, end] with its first reply (see the module docstring)."""
    s, e = as_datetime(start), as_datetime(end)
    now = _utc(now) or datetime.now(timezone.utc)
    rows = (
        db.query(Message.conversation_id, Message.direction, Message.channel, Message.created_at, Message.channel_metadata,
                 Message.delivery_state, Message.channel_status, Message.is_ai_generated, Message.sent_autonomously,
                 Message.sender_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .filter(Message.tenant_id == tenant_id, Conversation.tenant_id == tenant_id,
                Conversation.channel.in_([ChannelType.WHATSAPP, ChannelType.INSTAGRAM]),
                Conversation.is_sample.is_(False), Message.is_sample.is_(False), Message.is_internal.is_(False),
                Message.created_at >= s - TURN_GAP, Message.created_at <= min(e + REPLY_LOOKAHEAD, now))
        .order_by(Message.conversation_id, Message.created_at)
        .limit(MESSAGE_CAP + 1)
        .all()
    )
    truncated = len(rows) > MESSAGE_CAP
    turns: list[dict] = []
    too_recent = 0
    current_conv, prev_at, prev_inbound, open_turn = None, None, False, None
    for m in rows[:MESSAGE_CAP]:
        at = _utc(m.created_at)
        if m.conversation_id != current_conv:
            current_conv, prev_at, prev_inbound, open_turn = m.conversation_id, None, False, None
        if m.direction == MessageDirection.INBOUND:
            if _is_group(m):
                continue
            starts = prev_at is None or not prev_inbound or (at - prev_at) > TURN_GAP
            prev_at, prev_inbound = at, True
            if not starts:
                continue
            open_turn = None
            if s <= at <= e:
                if now - at < TOO_RECENT:
                    too_recent += 1
                    continue
                open_turn = {"at": at, "channel": _channel_of(m), "reply_seconds": None, "responder": None, "sender_id": None}
                turns.append(open_turn)
        else:
            if not _went_out(m):
                continue
            prev_at, prev_inbound = at, False
            if open_turn is not None:
                open_turn["reply_seconds"] = (at - open_turn["at"]).total_seconds()
                open_turn["responder"] = _responder(m)
                open_turn["sender_id"] = m.sender_id
                open_turn = None
    return {"turns": turns, "too_recent": too_recent, "truncated": truncated}


def summarise(turns: Iterable[dict]) -> dict:
    turns = list(turns)
    gaps = [t["reply_seconds"] for t in turns if t["reply_seconds"] is not None]
    within = {str(m): _pct(sum(1 for g in gaps if g <= m * 60), len(turns)) for m in TARGET_MINUTES}
    return {"turns": len(turns), "answered": len(gaps), "unanswered": len(turns) - len(gaps),
            "answered_pct": _pct(len(gaps), len(turns)), "median_seconds": percentile(gaps, 0.5),
            "p90_seconds": percentile(gaps, 0.9), "within_pct": within}


def first_replies(db: Session, tenant, start: Bound, end: Bound, *, now: Optional[datetime] = None) -> dict:
    """replies.first_response (all, per channel, per responder) and replies.after_hours, for one period."""
    found = guest_turns(db, tenant.id, start, end, now=now)
    turns = found["turns"]
    by_responder = {}
    for r in RESPONDERS:
        mine = [t for t in turns if t["responder"] == r]
        gaps = [t["reply_seconds"] for t in mine]
        by_responder[r] = {"answered": len(mine), "median_seconds": percentile(gaps, 0.5), "p90_seconds": percentile(gaps, 0.9),
                           "within_15_pct": _pct(sum(1 for g in gaps if g <= 900), len(mine))}
    after = [t for t in turns if not is_within_business_hours(tenant, t["at"])]
    after_answered = [t for t in after if t["reply_seconds"] is not None]
    by_ai = sum(1 for t in after_answered if t["responder"] == "ai")
    return {
        "all": summarise(turns),
        "by_channel": {c: summarise(t for t in turns if t["channel"] == c) for c in CHANNELS},
        "by_responder": by_responder,
        "after_hours": {"turns": len(after), "answered": len(after_answered),
                        "within_15_pct": _pct(sum(1 for t in after_answered if t["reply_seconds"] <= 900), len(after)),
                        "answered_by_ai": by_ai, "ai_share_pct": _pct(by_ai, len(after_answered)),
                        "median_seconds": percentile([t["reply_seconds"] for t in after_answered], 0.5)},
        "excluded_too_recent": found["too_recent"],
        "truncated": found["truncated"],
    }


# ── leads.quoted_cohort, with the existing cohort and enquiry counts ─────────────────────────────────────────

def _quoted_exists(tenant_id: str):
    i, q = aliased(Inquiry), aliased(InquiryQuote)
    return or_(
        exists().where(i.guest_id == Guest.id, i.tenant_id == tenant_id, q.inquiry_id == i.id, q.tenant_id == tenant_id),
        exists().where(i.guest_id == Guest.id, i.tenant_id == tenant_id, i.quoted_at.isnot(None)),
    )


def funnel(db: Session, tenant_id: str, start: Bound, end: Bound) -> dict:
    """Enquiry records in the period (enquiries.created) and the cohort of people who became leads in it: how many have been
    quoted (leads.quoted_cohort) and booked (leads.conversion_cohort) SO FAR. Enquiries and leads are never divided."""
    cohort = lead_metrics.cohort(db, tenant_id, start, end)
    quoted = int(db.query(func.count(Guest.id)).filter(*lead_metrics.new_leads_conditions(tenant_id, start, end),
                                                        _quoted_exists(tenant_id)).scalar() or 0)
    n = cohort["identified"]
    return {"enquiries": lead_metrics.enquiry_counts(db, tenant_id, start, end)["created"],
            "leads": n, "quoted": quoted, "booked": cohort["booked"],
            "lead_to_quote_pct": _pct(quoted, n), "lead_to_booking_pct": _pct(cohort["booked"], n)}


# ── calls.missed_returned ────────────────────────────────────────────────────────────────────────────────────

def missed_calls(db: Session, tenant_id: str, start: Bound, end: Bound) -> dict:
    """Inbound calls missed in the period (call_status_service rule), how many were called back (calls.recovered_by_call_id,
    whenever that happened) and how long the callback took. Every IVR provider's calls count (see D-15)."""
    back = aliased(Call)
    rows = (db.query(Call.created_at, back.created_at)
            .outerjoin(back, (back.id == Call.recovered_by_call_id) & (back.tenant_id == tenant_id))
            .filter(Call.tenant_id == tenant_id, Call.is_sample.is_(False), missed_call_sql_filter(),
                    Call.created_at >= as_datetime(start), Call.created_at <= as_datetime(end))
            .all())
    gaps = [max(0.0, (_utc(cb) - _utc(at)).total_seconds()) for at, cb in rows if cb is not None]
    return {"missed": len(rows), "returned": len(gaps), "returned_pct": _pct(len(gaps), len(rows)),
            "median_callback_seconds": percentile(gaps, 0.5),
            "within_60_pct": _pct(sum(1 for g in gaps if g <= 3600), len(rows))}


# ── enquiries.lost ───────────────────────────────────────────────────────────────────────────────────────────

def lost_enquiries(db: Session, tenant_id: str, start: Bound, end: Bound) -> dict:
    """Enquiry records (not spam) now in a closed-lost stage that entered it in the period, by the recorded reason."""
    entered = func.coalesce(Inquiry.current_stage_entered_at, Inquiry.updated_at)
    rows = (db.query(Inquiry.lost_reason, func.count(Inquiry.id))
            .join(PipelineStage, PipelineStage.id == Inquiry.stage_id)
            .filter(Inquiry.tenant_id == tenant_id, PipelineStage.tenant_id == tenant_id, PipelineStage.is_closed_lost.is_(True),
                    Inquiry.qualification_status != UNQUALIFIED, entered >= as_datetime(start), entered <= as_datetime(end))
            .group_by(Inquiry.lost_reason).all())
    by = defaultdict(int)
    for reason, n in rows:
        by[getattr(reason, "value", reason)] += int(n)
    items = [{"reason": k or "not_recorded", "label": LOST_REASON_LABELS.get(k, str(k).replace("_", " ").title()), "count": v}
             for k, v in sorted(by.items(), key=lambda kv: -kv[1])]
    return {"total": sum(by.values()), "by_reason": items}


# ── stays.booked / payments.collected per IST month ──────────────────────────────────────────────────────────

def _month_starts(first: date, last: date, cap: int = 24) -> list[date]:
    out, d = [], first.replace(day=1)
    while d <= last and len(out) < cap:
        out.append(d)
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def revenue_by_month(db: Session, tenant_id: str, first: date, last: date) -> list[dict]:
    """Per IST calendar month from ``first`` to ``last``: bookings made (stays.booked count and stay charge) and cash collected
    (payments.collected, refunds kept apart). The last month may be partial; ``to`` says where it stops."""
    months = []
    for m in _month_starts(first, last):
        nxt = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
        to = min(nxt - timedelta(days=1), last)
        s, e, _, _ = ist_range_to_utc(m.isoformat(), to.isoformat())
        count, value = kpi_metrics.booked_totals(db, tenant_id, s, e)
        cash = kpi_metrics.payment_totals(db, tenant_id, m, to)
        months.append({"month": m.strftime("%Y-%m"), "from": m.isoformat(), "to": to.isoformat(), "bookings": count,
                       "booked_value": round(value, 2), "collected": round(cash["collected"], 2),
                       "refunded": round(cash["refunded"], 2)})
    return months
