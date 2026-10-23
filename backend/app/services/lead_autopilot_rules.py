"""Lead autopilot: the deterministic rules (run first, before any AI).

Each rule reads facts HAIP already holds -- bookings, the inquiry's dates, quotes, calls and messages -- and returns at
most one Decision. The first rule that fires wins, in this order:

  1. booking_exists     a live booking (Stay) is linked to the lead           -> the tenant's closed-won stage (Sold)
  1b. collab_request    the guest asked for a collaboration / barter deal and
                        no person has answered (collab_requests.pending)    -> the tenant's collab-entry stage; while it
                        waits NO other rule runs, so it is never auto-Lost (lead_autopilot_service blocks an AI Lost too)
  2. dates_passed       check-in is in the past and nothing was booked        -> closed-lost, reason "dates"
  3. explicit_decline   a person set the call outcome to Lost, or the guest's
                        LATEST message is a clear decline ("not interested",
                        "booked elsewhere", "cancelled our plan")            -> closed-lost with the reason
  4. unanswered_calls   N unanswered outbound calls in a row across >= 2 days,
                        no reply on any channel since                       -> the tenant's "rnr" stage (only forward)
  5. quote_no_reply     a quote went out and the guest has said nothing since
                        for quote_silence_days                              -> closed-lost, reason "no_response"
  6. no_reply           the team contacted the guest last and nothing came
                        back for silence_days                               -> closed-lost, reason "no_response"
                        ("the team" = a person's message or our call; the AI's own replies, holding
                        lines and automatic messages never count: a guest waiting on us is not Lost)
  7. qualified          an Unqualified lead has a phone -> the valid-lead entry stage; a General Enquiry / RNR lead
                        with a phone AND a stated requirement (dates, route or headcount) -> the first open "valid"
                        stage after the entry (Active)

Stages are resolved from the tenant's own catalog by their flags (is_closed_won, is_closed_lost, is_valid_lead_entry,
is_default_entry, category) -- the only key used is "rnr", which has no flag (same lookup as lead_auto_create).
Only a LEAD (a guest with a usable phone, guests.lead_identified_at) is moved by rules 2-7; a plain DM is not a lead.
Event rules (3) only look at signals newer than the moment the lead entered its current stage, so a lead a person
re-opened is not pushed straight back. Guards (pinned, never backwards from Sold, live quote) live in the service.

Price phrases ("too expensive") are deliberately NOT a deterministic decline: they are usually a negotiation. The AI
classifier (lead_autopilot_ai) reads those with the rest of the conversation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

IST = ZoneInfo("Asia/Kolkata")
# Stages a "qualified" decision never targets, whatever their order: dead ends the work queue treats as done.
NEVER_QUALIFIED_KEYS = frozenset({"unsuitable"})


@dataclass
class Decision:
    to_stage: object                     # PipelineStage
    rule: str
    reason: str
    source: str = "rule"                 # rule | ai
    lost_reason: Optional[str] = None
    confidence: Optional[float] = 1.0
    evidence: list = field(default_factory=list)
    prompt_version: Optional[str] = None
    model: Optional[str] = None
    apply_allowed: bool = True           # False = suggestion only, whatever the mode (e.g. AI says "booked")


@dataclass
class StageMap:
    stages: list
    won: object = None
    lost: object = None
    default_entry: object = None
    valid_entry: object = None
    rnr: object = None
    qualified: object = None
    collab: object = None

    @classmethod
    def load(cls, db: Session, tenant_id: str) -> "StageMap":
        from app.models.pipeline_stage import PipelineStage
        stages = db.query(PipelineStage).filter_by(tenant_id=tenant_id).order_by(PipelineStage.order.asc()).all()
        m = cls(stages=stages)
        m.won = next((s for s in stages if s.is_closed_won), None)
        m.lost = next((s for s in stages if s.is_closed_lost), None)
        m.default_entry = next((s for s in stages if s.is_default_entry), None)
        m.valid_entry = next((s for s in stages if s.is_valid_lead_entry), None)
        m.rnr = next((s for s in stages if s.key == "rnr"), None)
        m.collab = next((s for s in stages if s.is_collab_entry), None)
        anchor = m.valid_entry.order if m.valid_entry else None
        # "unsuitable" is a dead end (the work queue treats it as done), never where a qualified lead goes. Ratha had
        # Unsuitable and Active at the same order, and the first one by order was Unsuitable: autopilot moved every
        # qualified lead there (20 Oct 2026). Prefer the stage keyed "active" when the tenant has one.
        open_valid = [s for s in stages if anchor is not None and s.order > anchor and (s.category or "valid") == "valid"
                      and not s.is_closed_won and not s.is_closed_lost and not s.is_collab_entry
                      and s.key not in NEVER_QUALIFIED_KEYS]
        m.qualified = next((s for s in open_valid if s.key == "active"), open_valid[0] if open_valid else None)
        return m

    def by_id(self, stage_id):
        return next((s for s in self.stages if s.id == stage_id), None)


# ── Explicit decline in the guest's own words ──────────────────────────────────────────────────────────────────────────
_DECLINE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(already\s+)?(booked|booking\s+done|confirmed)\s+(it\s+)?(elsewhere|somewhere\s+else|with\s+(another|some\s*one\s+else|a\s+different))", re.I), "booked_elsewhere"),
    (re.compile(r"\b(went|going)\s+with\s+(another|a\s+different|some\s*one\s+else)\b", re.I), "booked_elsewhere"),
    (re.compile(r"\b(no\s+longer|not)\s+(at\s+all\s+)?interested\b", re.I), "other"),
    (re.compile(r"\b(cancel+ed|dropped|drop(ping)?|postponed?|called\s+off)\s+(the|our|my)\s+(plan|trip)\b", re.I), "other"),
    (re.compile(r"\b(plan|trip)\s+(is\s+|got\s+|has\s+been\s+)?(cancel+ed|called\s+off|dropped)\b", re.I), "other"),
    (re.compile(r"\bnot\s+(planning|going\s+ahead|travelling|traveling)\b", re.I), "other"),
    (re.compile(r"\b(don'?t|do\s+not)\s+(need|want)\s+(it|this|the\s+caravan)\s*(any\s*more|now)?\b", re.I), "not_suitable"),
    (re.compile(r"\bnahi\s+chahiye\b", re.I), "other"),
]


def match_decline(text: Optional[str]) -> Optional[str]:
    """The lost-reason a guest message clearly declines with, or None. A question or a "but" means the guest is still
    talking (e.g. "not interested in the spa, but is the caravan free?"), so it is left to a person or the AI."""
    if not text or "?" in text or re.search(r"\b(but|however|instead|maybe)\b", text, re.I):
        return None
    for pattern, reason in _DECLINE_PATTERNS:
        if pattern.search(text):
            return reason
    return None


_CALL_LOST_REASON = {
    "price": "price", "budget_mismatch": "price", "dates_unavailable": "dates", "wrong_dates": "dates",
    "no_response": "no_response", "wrong_property": "not_suitable", "chose_competitor": "booked_elsewhere",
}


# ── Signal helpers ─────────────────────────────────────────────────────────────────────────────────────────────────────
def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_date(value) -> Optional[date]:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _value(v) -> str:
    return str(getattr(v, "value", v) or "").lower()


@dataclass
class Signals:
    has_phone: bool
    stays: list
    calls: list                  # newest first, this guest
    last_inbound: object         # Message or None (guest's latest real message)
    last_outbound: object        # Message or None (latest message a PERSON sent or approved: the contact rule)
    quotes: list                 # newest first
    stage_entered_at: Optional[datetime]
    collab_ask: object = None    # a collaboration request no person has answered (collab_requests.pending)


def gather(db: Session, tenant_id: str, inquiry) -> Signals:
    from sqlalchemy import or_
    from app.models.call import Call
    from app.models.conversation import Conversation, Message, MessageDirection
    from app.models.guest import Guest
    from app.models.inquiry_360 import InquiryQuote
    from app.models.property import Stay

    guest = db.query(Guest).filter_by(id=inquiry.guest_id, tenant_id=tenant_id).first()
    stays = [s for s in db.query(Stay).filter_by(tenant_id=tenant_id, inquiry_id=inquiry.id).all() if s.status != "cancelled"]
    calls = (db.query(Call).filter_by(tenant_id=tenant_id, guest_id=inquiry.guest_id)
             .order_by(Call.created_at.desc()).limit(20).all())
    conv_ids = [r[0] for r in db.query(Conversation.id).filter(
        Conversation.tenant_id == tenant_id,
        or_(Conversation.inquiry_id == inquiry.id, Conversation.guest_id == inquiry.guest_id)).all()]
    last_in = last_out = None
    if conv_ids:
        base = db.query(Message).filter(Message.tenant_id == tenant_id, Message.conversation_id.in_(conv_ids),
                                        Message.is_internal.is_(False))
        last_in = base.filter(Message.direction == MessageDirection.INBOUND).order_by(Message.created_at.desc()).first()
        # Our contact = the ONE contact rule (work_queue_signals): a message a PERSON sent or approved. The AI's own replies and
        # holding lines, playbook/system messages and campaign broadcasts (old rows too) are not: a guest waiting on US must
        # never read as "we spoke last, they went silent" (live: the AI's "we'll get back to you" made a waiting guest Lost).
        from app.services.work_queue_signals import contact_message_filters, is_legacy_campaign
        last_out = next((m for m in base.filter(*contact_message_filters()).order_by(Message.created_at.desc()).limit(20)
                         if not is_legacy_campaign(m.sender_name, m.channel_metadata)), None)
    quotes = (db.query(InquiryQuote).filter_by(tenant_id=tenant_id, inquiry_id=inquiry.id)
              .order_by(InquiryQuote.created_at.desc()).all())
    from app.services import collab_requests
    collab_ask = collab_requests.pending(db, tenant_id, conv_ids, inquiry.guest_id)
    return Signals(
        has_phone=bool(guest is not None and guest.lead_identified_at is not None),
        stays=stays, calls=calls, last_inbound=last_in, last_outbound=last_out, quotes=quotes,
        stage_entered_at=_aware(inquiry.current_stage_entered_at or inquiry.created_at),
        collab_ask=collab_ask,
    )


def _guest_engaged_at(sig: Signals) -> Optional[datetime]:
    """When the guest last engaged: a message from them or a call that connected."""
    from app.services import call_status_service as cs
    times = [_aware(sig.last_inbound.created_at)] if sig.last_inbound is not None else []
    for call in sig.calls:
        direction = _value(call.direction)
        answered = cs.is_answered_call(call) if direction == "inbound" else not cs.is_unanswered_outbound(call)
        if answered:
            times.append(_aware(call.created_at))
            break
    return max(times) if times else None


def _team_contacted_at(sig: Signals) -> Optional[datetime]:
    times = [_aware(sig.last_outbound.created_at)] if sig.last_outbound is not None else []
    times += [_aware(c.created_at) for c in sig.calls[:1] if _value(c.direction) == "outbound"]
    return max(times) if times else None


def _unanswered_streak(sig: Signals) -> list:
    from app.services import call_status_service as cs
    streak = []
    for call in sig.calls:
        if _value(call.direction) != "outbound" or not cs.is_unanswered_outbound(call):
            break
        streak.append(call)
    if streak and sig.last_inbound is not None and _aware(sig.last_inbound.created_at) > _aware(streak[-1].created_at):
        return []          # they wrote to us after the first unanswered call: still engaged
    return streak


def _snippet(text: Optional[str]) -> str:
    return " ".join((text or "").split())[:200]


# ── The rules ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def evaluate(db: Session, tenant_id: str, inquiry, stages: StageMap, settings: dict,
             now: Optional[datetime] = None) -> Optional[Decision]:
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(IST).date()
    current = stages.by_id(inquiry.stage_id)
    if current is None or current.is_closed_won or current.is_closed_lost or current.is_collab_entry:
        return None
    sig = gather(db, tenant_id, inquiry)

    # 1. A live booking means the lead was sold, phone or not.
    if sig.stays and stages.won is not None:
        stay = sig.stays[0]
        return Decision(stages.won, "booking_exists", f"A booking ({stay.check_in}) is linked to this lead",
                        evidence=[{"kind": "booking", "id": stay.id, "quote": f"Booking {stay.check_in} to {stay.check_out}"}])

    # 1b. A collaboration / barter request waiting for a person: the collab stage, never a sales Lost. A request older than a
    # person's own move of the lead is not moved again; either way nothing else is decided while it waits.
    ask = sig.collab_ask
    if ask is not None:
        if stages.collab is not None and (sig.stage_entered_at is None or _aware(ask.created_at) >= sig.stage_entered_at):
            return Decision(stages.collab, "collab_request", "The guest asked for a collaboration / barter deal; a person decides",
                            evidence=[{"kind": "message", "id": ask.id, "quote": _snippet(ask.body)}])
        return None

    if not sig.has_phone or stages.lost is None:
        return _qualify(inquiry, stages, current, sig)

    # 2. Travel dates gone by, nothing booked.
    check_in = _parse_date(inquiry.check_in)
    if check_in is not None and check_in < today:
        return Decision(stages.lost, "dates_passed", f"The travel date ({check_in:%d %b}) passed without a booking",
                        lost_reason="dates",
                        evidence=[{"kind": "inquiry", "id": inquiry.id, "quote": f"Check-in {check_in.isoformat()}"}])

    # 3. An explicit decline, newer than the lead's current stage.
    entered = sig.stage_entered_at
    newest_call = sig.calls[0] if sig.calls else None
    if newest_call is not None and (entered is None or _aware(newest_call.created_at) >= entered):
        if _value(newest_call.human_disposition) == "lost":
            reason = _CALL_LOST_REASON.get(_value(newest_call.lost_reason), "other")
            return Decision(stages.lost, "explicit_decline", "A team member marked the last call as lost",
                            lost_reason=reason,
                            evidence=[{"kind": "call", "id": newest_call.id,
                                       "quote": _snippet(newest_call.disposition_note or newest_call.ai_summary)}])
    msg = sig.last_inbound
    if msg is not None and (entered is None or _aware(msg.created_at) >= entered):
        declined = match_decline(msg.body)
        if declined:
            return Decision(stages.lost, "explicit_decline", "The guest declined in their last message",
                            lost_reason=declined,
                            evidence=[{"kind": "message", "id": msg.id, "quote": _snippet(msg.body)}])

    # 4. Ringing, no response.
    streak = _unanswered_streak(sig)
    days = {_aware(c.created_at).astimezone(IST).date() for c in streak}
    if (len(streak) >= int(settings["unanswered_calls"]) and len(days) >= 2
            and stages.rnr is not None and stages.rnr.order > current.order):
        return Decision(stages.rnr, "unanswered_calls",
                        f"{len(streak)} calls in a row went unanswered over {len(days)} days, with no reply since",
                        evidence=[{"kind": "call", "id": c.id, "quote": "Unanswered outbound call"} for c in streak[:5]])

    engaged = _guest_engaged_at(sig)
    contacted = _team_contacted_at(sig)

    # 5. Quote sent, silence.
    quote = sig.quotes[0] if sig.quotes else None
    quote_at = _aware(quote.created_at) if quote is not None else None
    if quote_at is not None and now - quote_at >= timedelta(days=int(settings["quote_silence_days"])) \
            and (engaged is None or engaged <= quote_at):
        return Decision(stages.lost, "quote_no_reply",
                        f"No reply in {(now - quote_at).days} days since the quote was sent", lost_reason="no_response",
                        evidence=[{"kind": "quote", "id": quote.id, "quote": f"Quote of ₹{quote.amount} sent {quote_at.date()}"}])

    # 6. The team reached out last and nothing came back.
    # Silence is counted from the guest's last word (or the enquiry), and our last attempt must be 2+ days old so a
    # message sent yesterday still gets its chance to be answered.
    silent_since = engaged or _aware(inquiry.created_at) or now
    if contacted is not None and (engaged is None or engaged < contacted) \
            and now - silent_since >= timedelta(days=int(settings["silence_days"])) \
            and now - contacted >= timedelta(days=2):
        ev = []
        if sig.last_outbound is not None:
            ev.append({"kind": "message", "id": sig.last_outbound.id, "quote": _snippet(sig.last_outbound.body)})
        return Decision(stages.lost, "no_reply",
                        f"No reply from the guest for {(now - silent_since).days} days, after our last contact",
                        lost_reason="no_response", evidence=ev)

    return _qualify(inquiry, stages, current, sig)


def _qualify(inquiry, stages: StageMap, current, sig: Signals) -> Optional[Decision]:
    if not sig.has_phone:
        return None
    if stages.default_entry is not None and current.id == stages.default_entry.id:
        if stages.valid_entry is not None and stages.valid_entry.order > current.order:
            return Decision(stages.valid_entry, "qualified", "The guest shared a usable phone number",
                            evidence=[{"kind": "inquiry", "id": inquiry.id, "quote": "Phone number on file"}])
        return None
    requirement = [label for label, val in (("dates", inquiry.check_in), ("route", inquiry.route_mentioned),
                                            ("guests", inquiry.adults)) if val]
    target = stages.qualified
    if not requirement or target is None or target.order <= current.order:
        return None
    in_entry = stages.valid_entry is not None and current.id == stages.valid_entry.id
    in_rnr = stages.rnr is not None and current.id == stages.rnr.id
    if not (in_entry or in_rnr):
        return None
    if in_rnr:
        engaged = _guest_engaged_at(sig)
        if engaged is None or (sig.stage_entered_at and engaged < sig.stage_entered_at):
            return None          # still not answering: stays in RNR
    return Decision(target, "qualified", f"Phone and requirement captured ({', '.join(requirement)})",
                    evidence=[{"kind": "inquiry", "id": inquiry.id,
                               "quote": "; ".join(f"{k}: {v}" for k, v in (("check-in", inquiry.check_in),
                                                                        ("route", inquiry.route_mentioned),
                                                                        ("adults", inquiry.adults)) if v)}])
