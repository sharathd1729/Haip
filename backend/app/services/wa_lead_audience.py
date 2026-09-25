"""
Who a WhatsApp campaign to CRM leads goes to.

A campaign used to reach only a separate "subscribers" list that someone had to
import by hand, while the leads with phone numbers sat in the CRM. This resolves
an audience straight from the leads: filters over stage, source, owner, dates and
what the AI has already read from each chat (mood, urgency, trip dates, group
size, occasion, quote), then takes out everyone who can't or shouldn't be
messaged -- and says how many, and why.

"Heat" is a plain, explainable score over those same signals. It is a first cut
that uses only what the CRM already holds; every point it awards is listed so a
person can see why a lead is hot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.services.wa_campaign_schedule import IST
from app.services.wa_subscriber_import import validate_phone

MAX_LEADS = 50_000
HOT_AT = 6
WARM_AT = 3
HEATS = ("hot", "warm", "cold")

UNASSIGNED = "unassigned"


# ─── Heat ────────────────────────────────────────────────────────────────────

def score_lead(
    *,
    sentiment: Optional[str] = None,
    urgency: Optional[str] = None,
    quoted_open: bool = False,
    days_to_checkin: Optional[int] = None,
    adults: Optional[int] = None,
    occasion: Optional[str] = None,
    budget_stated: bool = False,
    inbound_messages: int = 0,
    closed_lost: bool = False,
) -> tuple[int, str, list[str]]:
    """(score, heat, reasons). Each reason is a point someone can read."""
    if closed_lost:
        return 0, "cold", ["Already marked lost"]
    score, why = 0, []

    def add(points: int, reason: str) -> None:
        nonlocal score
        score += points
        why.append(reason)

    if quoted_open:
        add(3, "Has a quote and hasn't booked yet")
    if sentiment == "positive":
        add(2, "Positive tone")
    elif sentiment == "negative":
        add(-2, "Negative tone")
    elif sentiment == "hesitant":
        add(-1, "Hesitant")
    if urgency == "high":
        add(2, "Needs a quick reply")
    elif urgency == "medium":
        add(1, "Wants a reply")
    if days_to_checkin is not None and days_to_checkin >= 0:
        if days_to_checkin <= 45:
            add(2, f"Trip in {days_to_checkin} days")
        elif days_to_checkin <= 90:
            add(1, "Trip within 3 months")
    if adults:
        add(1, "Gave a group size")
    if occasion:
        add(1, f"Occasion: {occasion}")
    if budget_stated:
        add(1, "Stated a budget")
    if inbound_messages >= 8:
        add(2, "Very engaged in chat")
    elif inbound_messages >= 3:
        add(1, "Engaged in chat")

    heat = "hot" if score >= HOT_AT else "warm" if score >= WARM_AT else "cold"
    return score, heat, why


# ─── Filter ──────────────────────────────────────────────────────────────────

PRESETS = [
    {"id": "hot", "label": "Hot leads", "description": "Positive, engaged and close to booking",
     "filter": {"heat": ["hot"]}},
    {"id": "quoted", "label": "Quoted, not booked", "description": "Got a price and haven't confirmed",
     "filter": {"quoted_open": True}},
    {"id": "trip_soon", "label": "Travelling soon", "description": "Asked about dates in the next 45 days",
     "filter": {"trip_within_days": 45}},
    {"id": "went_quiet", "label": "Went quiet", "description": "Were warm or hot, no activity for a week",
     "filter": {"heat": ["hot", "warm"], "quiet_days_min": 7}},
    {"id": "new_week", "label": "New this week", "description": "Enquired in the last 7 days",
     "filter": {"created_within_days": 7}},
    {"id": "past_guests", "label": "Past guests", "description": "Stayed with you before",
     "filter": {"past_guests": True}},
]


def _ints(v: Any, lo: int, hi: int) -> Optional[int]:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


def _str_list(v: Any, limit: int = 100) -> list[str]:
    if not isinstance(v, (list, tuple)):
        return []
    return [str(x).strip() for x in v if str(x).strip()][:limit]


def _iso_date(v: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def normalize_filter(raw: Optional[dict]) -> dict:
    """The filter as it will be used: only known keys, sane values. Anything
    else the client sent is dropped, so a filter is never a way to reach data
    the audience code doesn't intend to expose."""
    raw = raw or {}
    out: dict[str, Any] = {}
    if (heat := [h for h in _str_list(raw.get("heat")) if h in HEATS]):
        out["heat"] = heat
    for key in ("stage_ids", "sources", "assigned_to", "occasions"):
        if (vals := _str_list(raw.get(key))):
            out[key] = vals
    for key, hi in (("trip_within_days", 730), ("quiet_days_min", 3650), ("not_messaged_days", 3650), ("created_within_days", 3650)):
        if (n := _ints(raw.get(key), 0, hi)) is not None and (n > 0 or key == "trip_within_days"):
            out[key] = n
    for key in ("created_from", "created_to"):
        if (d := _iso_date(raw.get(key))):
            out[key] = d.isoformat()
    for key in ("quoted_open", "past_guests"):
        if raw.get(key) is True:
            out[key] = True
    return out


class AudienceError(ValueError):
    """An audience the user has to fix; message is safe to show."""


def prepare_audience_filter(raw: Optional[dict]) -> dict:
    """The audience to store on a campaign. A CRM-leads audience must carry the
    sender's confirmation that these people contacted the business and haven't
    asked to stop -- messaging leads is a consent decision, so it is asked for
    every time and kept with the campaign. Subscriber audiences keep their
    existing shape."""
    raw = raw or {}
    if raw.get("type") != "leads":
        return raw
    if raw.get("consent_confirmed") is not True:
        raise AudienceError("Confirm these leads have contacted you and haven't asked you to stop before continuing.")
    return {"type": "leads", **normalize_filter(raw), "consent_confirmed": True}


# ─── Resolve ─────────────────────────────────────────────────────────────────

@dataclass
class Member:
    """One person a campaign will message. Duck-typed like WASubscriber
    (phone, name) so the runner and variable mapping treat both the same."""
    phone: str
    name: Optional[str]
    guest_id: Optional[str] = None
    id: Optional[str] = None                # subscriber id, when the audience is a subscriber list
    heat: Optional[str] = None
    score: int = 0
    why: list[str] = field(default_factory=list)


@dataclass
class AudienceResult:
    members: list[Member]
    matched: int = 0                        # people who matched the filters, before anyone is taken out
    no_phone: int = 0
    invalid_phone: int = 0
    opted_out: int = 0
    recently_messaged: int = 0
    truncated: bool = False

    def breakdown(self) -> dict:
        return {
            "matched": self.matched, "will_receive": len(self.members),
            "no_phone": self.no_phone, "invalid_phone": self.invalid_phone,
            "opted_out": self.opted_out, "recently_messaged": self.recently_messaged,
            "truncated": self.truncated,
        }


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _ist_day_start(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=IST).astimezone(timezone.utc)


def resolve(db: Session, tenant_id: str, audience_filter: Optional[dict], now: Optional[datetime] = None) -> AudienceResult:
    from app.models.consent import Consent
    from app.models.conversation import Conversation, Message, MessageDirection
    from app.models.guest import Guest
    from app.models.inquiry import Inquiry, InquirySource
    from app.models.pipeline_stage import PipelineStage
    from app.models.wa_campaign_recipient import WACampaignRecipient
    from app.api.v1.endpoints.messaging import WASubscriber

    f = normalize_filter(audience_filter)
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(IST).date()
    stages = {s.id: s for s in db.query(PipelineStage).filter_by(tenant_id=tenant_id)}

    q = (
        db.query(Inquiry, Guest)
        .join(Guest, Guest.id == Inquiry.guest_id)
        .filter(
            Inquiry.tenant_id == tenant_id, Guest.tenant_id == tenant_id,
            Guest.is_deleted.is_(False), Guest.is_sample.is_(False), Guest.deletion_state == "none",
        )
    )
    if f.get("stage_ids"):
        q = q.filter(Inquiry.stage_id.in_(f["stage_ids"]))
    if f.get("sources"):
        valid = []
        for s in f["sources"]:
            try:
                valid.append(InquirySource(s))
            except ValueError:
                pass
        q = q.filter(Inquiry.source.in_(valid)) if valid else q.filter(False)
    if f.get("assigned_to"):
        ids = [a for a in f["assigned_to"] if a != UNASSIGNED]
        conds = []
        if ids:
            conds.append(Inquiry.assigned_to.in_(ids))
        if UNASSIGNED in f["assigned_to"]:
            conds.append(Inquiry.assigned_to.is_(None))
        q = q.filter(or_(*conds))
    if f.get("occasions"):
        q = q.filter(func.lower(Inquiry.occasion).in_([o.lower() for o in f["occasions"]]))
    created_from = f.get("created_from")
    if f.get("created_within_days"):
        created_from = (today - timedelta(days=f["created_within_days"])).isoformat()
    if created_from:
        q = q.filter(Inquiry.created_at >= _ist_day_start(date.fromisoformat(created_from)))
    if f.get("created_to"):
        q = q.filter(Inquiry.created_at < _ist_day_start(date.fromisoformat(f["created_to"]) + timedelta(days=1)))

    rows = q.limit(MAX_LEADS + 1).all()
    result = AudienceResult(members=[], truncated=len(rows) > MAX_LEADS)
    rows = rows[:MAX_LEADS]

    inbound = dict(
        db.query(Conversation.guest_id, func.count(Message.id))
        .join(Message, Message.conversation_id == Conversation.id)
        .filter(Conversation.tenant_id == tenant_id, Message.direction == MessageDirection.INBOUND)
        .group_by(Conversation.guest_id).all()
    )

    best: dict[str, tuple[int, str, list[str], Any]] = {}       # guest_id -> (score, heat, why, guest)
    for inq, guest in rows:
        stage = stages.get(inq.stage_id)
        analysis = inq.ai_analysis if isinstance(inq.ai_analysis, dict) else {}
        days_to = None
        if inq.check_in:
            ci = _iso_date(inq.check_in)
            days_to = (ci - today).days if ci else None
        quoted_open = inq.quoted_amount is not None and not (stage and (stage.is_closed_won or stage.is_closed_lost))
        score, heat, why = score_lead(
            sentiment=analysis.get("sentiment"), urgency=analysis.get("reply_urgency"), quoted_open=quoted_open,
            days_to_checkin=days_to, adults=inq.adults, occasion=inq.occasion, budget_stated=inq.budget is not None,
            inbound_messages=inbound.get(guest.id, 0), closed_lost=bool(stage and stage.is_closed_lost),
        )
        # ── filters that need the computed signals ──
        if f.get("heat") and heat not in f["heat"]:
            continue
        if "trip_within_days" in f and not (days_to is not None and 0 <= days_to <= f["trip_within_days"]):
            continue
        if f.get("quiet_days_min"):
            touched = _aware(inq.updated_at)
            if touched is None or (now - touched).days < f["quiet_days_min"]:
                continue
        if f.get("quoted_open") and not quoted_open:
            continue
        if f.get("past_guests") and not ((stage and stage.is_closed_won) or (guest.total_stays or 0) > 0):
            continue
        cur = best.get(guest.id)
        if cur is None or score > cur[0]:
            best[guest.id] = (score, heat, why, guest)

    result.matched = len(best)

    # ── who can't or shouldn't be messaged ──
    withdrawn = {
        r[0] for r in db.query(Consent.guest_id).filter(
            Consent.tenant_id == tenant_id, Consent.scope == "marketing", Consent.granted.is_(False))
    }
    opted_out_phones = {
        r[0] for r in db.query(WASubscriber.phone).filter(
            WASubscriber.tenant_id == tenant_id, WASubscriber.opted_in.is_(False))
    }
    recent_phones: set[str] = set()
    if f.get("not_messaged_days"):
        since = now - timedelta(days=f["not_messaged_days"])
        recent_phones = {
            r[0] for r in db.query(WACampaignRecipient.phone).filter(
                WACampaignRecipient.tenant_id == tenant_id,
                WACampaignRecipient.status.in_(("sent", "delivered", "read")),
                WACampaignRecipient.sent_at >= since)
        }

    seen_phones: set[str] = set()
    for guest_id, (score, heat, why, guest) in best.items():
        raw_phone = (guest.phone or "").strip()
        if not raw_phone:
            result.no_phone += 1
            continue
        phone, problem = validate_phone(raw_phone)
        if problem:
            result.invalid_phone += 1
            continue
        if guest_id in withdrawn or phone in opted_out_phones:
            result.opted_out += 1
            continue
        if phone in recent_phones:
            result.recently_messaged += 1
            continue
        if phone in seen_phones:                       # two guest records, one number
            continue
        seen_phones.add(phone)
        result.members.append(Member(phone=phone, name=guest.name, guest_id=guest_id, heat=heat, score=score, why=why))

    result.members.sort(key=lambda m: (-m.score, (m.name or "").lower()))
    return result


# ─── Options for the form ────────────────────────────────────────────────────

def options(db: Session, tenant_id: str) -> dict:
    """What the audience picker offers, with how many leads are behind each
    choice -- counted as people, and how many of them have a phone number."""
    from app.models.guest import Guest
    from app.models.inquiry import Inquiry
    from app.models.pipeline_stage import PipelineStage
    from app.models.user import User

    base = (
        db.query(Inquiry.stage_id, Inquiry.source, Inquiry.assigned_to, Guest.id, Guest.phone)
        .join(Guest, Guest.id == Inquiry.guest_id)
        .filter(Inquiry.tenant_id == tenant_id, Guest.tenant_id == tenant_id,
                Guest.is_deleted.is_(False), Guest.is_sample.is_(False), Guest.deletion_state == "none")
        .limit(MAX_LEADS).all()
    )
    stage_people: dict[Any, set] = {}
    source_people: dict[Any, set] = {}
    owner_people: dict[Any, set] = {}
    with_phone: set[str] = set()
    everyone: set[str] = set()
    for stage_id, source, owner, guest_id, phone in base:
        everyone.add(guest_id)
        has = bool((phone or "").strip())
        if has:
            with_phone.add(guest_id)
        stage_people.setdefault(stage_id, set()).add((guest_id, has))
        source_people.setdefault(source.value if source else None, set()).add((guest_id, has))
        owner_people.setdefault(owner, set()).add((guest_id, has))

    def tally(people: set) -> dict:
        return {"leads": len({g for g, _ in people}), "with_phone": len({g for g, h in people if h})}

    stages = [
        {"id": s.id, "key": s.key, "label": s.label, "category": s.category, **tally(stage_people.get(s.id, set()))}
        for s in db.query(PipelineStage).filter_by(tenant_id=tenant_id).order_by(PipelineStage.order)
    ]
    users = {u.id: u.name for u in db.query(User).filter_by(tenant_id=tenant_id)}
    return {
        "totals": {"leads": len(everyone), "with_phone": len(with_phone)},
        "presets": PRESETS,
        "stages": stages,
        "sources": sorted(
            [{"value": v, "label": (v or "unknown").replace("_", " "), **tally(p)} for v, p in source_people.items() if v],
            key=lambda x: -x["leads"]),
        "owners": sorted(
            [{"id": k or UNASSIGNED, "name": users.get(k, "Unknown") if k else "Unassigned", **tally(p)} for k, p in owner_people.items()],
            key=lambda x: -x["leads"]),
    }
