"""IVR call routing: which agent number(s) an inbound call should dial.

The agent pool is existing HAIP users with `ivr_call_routing_enabled=True`
and a phone number on file -- not a separate number list. See migration 084
and CLAUDE.md's framing of agents as real system users taking calls on their
personal mobile via IVR.

Strategy names match Vobiz's own console call-distribution picker
(Simultaneous ringing / Round Robin / Fixed order / Longest idle / Sticky
agent) -- built here on our own Answer URL webhook rather than Vobiz's
native Team routing feature, since Vobiz's docs describe recording and
webhooks as the customer's own responsibility and don't confirm whether
their console-level Team routing still invokes the Answer URL. Routing here
keeps every call guaranteed to hit call_ingest (record -> transcribe ->
analyze) regardless of strategy.

Numbers returned here are raw (whatever's in User.phone) -- provider-specific
E.164 normalization (e.g. webhooks_vobiz.py's _to_e164_in) stays with the
caller, since different IVR providers may have different formatting quirks.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core import cache
from app.models.user import User
from app.models.tenant import Tenant
from app.services import media_storage

STRATEGY_SINGLE = "single"
STRATEGY_ROUND_ROBIN = "round_robin"
STRATEGY_PARALLEL = "parallel"
STRATEGY_FIXED_ORDER = "fixed_order"
STRATEGY_LONGEST_IDLE = "longest_idle"
STRATEGY_STICKY_AGENT = "sticky_agent"
VALID_STRATEGIES = (
    STRATEGY_SINGLE, STRATEGY_ROUND_ROBIN, STRATEGY_PARALLEL,
    STRATEGY_FIXED_ORDER, STRATEGY_LONGEST_IDLE, STRATEGY_STICKY_AGENT,
)

# Strategies that ring several numbers in the same <Dial> (simultaneous)
# vs. ringing every candidate but only one at a time, one after another,
# rendered as separate sequential <Dial> verbs (webhooks_vobiz.py).
_SEQUENTIAL_STRATEGIES = (STRATEGY_FIXED_ORDER,)

_STICKY_TTL = 60 * 60 * 24 * 90  # 90 days -- long enough to cover a repeat guest's whole trip lifecycle


def _get_eligible_agents(db: Session, tenant_id: str) -> list[User]:
    """Users opted into call routing, active, not soft-deleted, with a phone
    number. Ordered by created_at/id for a deterministic sequence (not
    name -- an agent shouldn't jump the queue by renaming themselves)."""
    return (
        db.query(User)
        .filter(
            User.tenant_id == tenant_id,
            User.ivr_call_routing_enabled.is_(True),
            User.is_active.is_(True),
            User.is_deleted.is_(False),
            User.phone.isnot(None),
            User.phone != "",
        )
        .order_by(User.created_at, User.id)
        .all()
    )


def get_eligible_agent_numbers(db: Session, tenant_id: str) -> list[str]:
    return [u.phone for u in _get_eligible_agents(db, tenant_id) if u.phone]


def _mark_dialed(db: Session, agents: list[User]) -> None:
    if not agents:
        return
    now = datetime.now(timezone.utc)
    for a in agents:
        a.ivr_last_dialed_at = now
    db.commit()


def _round_robin_pick(tenant_id: str, agents: list[User]) -> User:
    if len(agents) == 1:
        return agents[0]
    n = cache.incr(f"haip:ivr:rr:{tenant_id}")
    if n is None:
        # Redis unreachable -- degrade to always-first rather than random,
        # so behaviour under a cache outage is at least predictable.
        n = 0
    return agents[n % len(agents)]


def _longest_idle_pick(agents: list[User]) -> User:
    """Whoever has gone longest without being dialed -- never-dialed (None)
    sorts first, i.e. counts as the most idle."""
    def _key(a: User) -> datetime:
        dt = a.ivr_last_dialed_at
        if dt is None:
            return datetime.min
        # Postgres round-trips DateTime(timezone=True) as aware; SQLite (the
        # test DB) round-trips it naive -- comparing values that differ in
        # tz-awareness raises, so normalize to naive for this comparison
        # only. Every real value is already written in UTC (_mark_dialed),
        # so dropping tzinfo doesn't change relative ordering.
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    return min(agents, key=_key)


def _sticky_key(tenant_id: str, caller_number: str) -> str:
    return f"haip:ivr:sticky:{tenant_id}:{caller_number}"


def _sticky_agent_pick(tenant_id: str, caller_number: str | None, agents: list[User]) -> User:
    """Route a repeat caller back to whoever they were routed to last time,
    if that agent is still eligible. First-time callers (or a stale/no-
    longer-eligible previous agent) fall back to round robin, which also
    becomes the new sticky pick for next time."""
    if caller_number:
        sticky_phone = cache.get_cached(_sticky_key(tenant_id, caller_number))
        if sticky_phone:
            match = next((a for a in agents if a.phone == sticky_phone), None)
            if match:
                return match
    picked = _round_robin_pick(tenant_id, agents)
    if caller_number:
        cache.set_cached(_sticky_key(tenant_id, caller_number), picked.phone, ttl=_STICKY_TTL)
    return picked


def resolve_dial_numbers(
    db: Session, tenant: Tenant, fallback_number: str | None = None, caller_number: str | None = None,
) -> list[str]:
    """The raw phone number(s) to dial for one inbound call, in the order
    the caller should be attempted (relevant for fixed_order; a single
    entry for every other non-parallel strategy).

    Falls back to `fallback_number` (the pre-existing single Integration
    credential) whenever no eligible agents are configured yet, so shipping
    this doesn't change behaviour for a tenant that hasn't opted any user
    into routing -- exactly today's single-number dial.
    """
    agents = _get_eligible_agents(db, tenant.id)
    if not agents:
        return [fallback_number] if fallback_number else []

    strategy = tenant.ivr_routing_strategy or STRATEGY_SINGLE

    if strategy in (STRATEGY_PARALLEL, STRATEGY_FIXED_ORDER):
        _mark_dialed(db, agents)
        return [a.phone for a in agents]

    if strategy == STRATEGY_ROUND_ROBIN:
        picked = _round_robin_pick(tenant.id, agents)
    elif strategy == STRATEGY_LONGEST_IDLE:
        picked = _longest_idle_pick(agents)
    elif strategy == STRATEGY_STICKY_AGENT:
        picked = _sticky_agent_pick(tenant.id, caller_number, agents)
    else:
        picked = agents[0]

    _mark_dialed(db, [picked])
    return [picked.phone]


def dial_mode(tenant: Tenant) -> str:
    """"sequential" (try each candidate one at a time, moving to the next
    only if the current one isn't answered) vs "simultaneous" (ring every
    candidate at once in one <Dial>, first pick wins) -- webhooks_vobiz.py
    uses this to choose the XML shape. Every strategy but fixed_order and
    parallel resolves to exactly one number, where the distinction is moot."""
    strategy = tenant.ivr_routing_strategy or STRATEGY_SINGLE
    return "sequential" if strategy in _SEQUENTIAL_STRATEGIES else "simultaneous"


def resolve_greeting_url(tenant: Tenant, expires_in: int = 300) -> str | None:
    """Presigned URL for the client-uploaded greeting MP3, or None if no
    greeting is configured. Short expiry is fine and safer than a public
    bucket -- Vobiz fetches the URL immediately when it renders the answer
    XML, it doesn't hold onto it."""
    if not tenant.ivr_greeting_audio_key:
        return None
    return media_storage.get_presigned_media_url(tenant.ivr_greeting_audio_key, expires_in=expires_in)
