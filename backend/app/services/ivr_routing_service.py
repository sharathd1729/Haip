"""IVR call routing: which agent number(s) an inbound call should dial.

The agent pool is existing HAIP users with `ivr_call_routing_enabled=True`
and a phone number on file -- not a separate number list. See migration 084
and CLAUDE.md's framing of agents as real system users taking calls on their
personal mobile via IVR.

Numbers returned here are raw (whatever's in User.phone) -- provider-specific
E.164 normalization (e.g. webhooks_vobiz.py's _to_e164_in) stays with the
caller, since different IVR providers may have different formatting quirks.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.core import cache
from app.models.user import User
from app.models.tenant import Tenant
from app.services import media_storage

STRATEGY_SINGLE = "single"
STRATEGY_ROUND_ROBIN = "round_robin"
STRATEGY_PARALLEL = "parallel"
VALID_STRATEGIES = (STRATEGY_SINGLE, STRATEGY_ROUND_ROBIN, STRATEGY_PARALLEL)


def get_eligible_agent_numbers(db: Session, tenant_id: str) -> list[str]:
    """Users opted into call routing, active, not soft-deleted, with a phone
    number. Ordered by created_at/id for a deterministic rotation sequence
    (not name -- an agent shouldn't jump the queue by renaming themselves)."""
    users = (
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
    return [u.phone for u in users if u.phone]


def _round_robin_pick(tenant_id: str, numbers: list[str]) -> str:
    if len(numbers) == 1:
        return numbers[0]
    n = cache.incr(f"haip:ivr:rr:{tenant_id}")
    if n is None:
        # Redis unreachable -- degrade to always-first rather than random,
        # so behaviour under a cache outage is at least predictable.
        n = 0
    return numbers[n % len(numbers)]


def resolve_dial_numbers(
    db: Session, tenant: Tenant, fallback_number: str | None = None,
) -> list[str]:
    """The raw phone number(s) to dial for one inbound call.

    Falls back to `fallback_number` (the pre-existing single Integration
    credential) whenever no eligible agents are configured yet, so shipping
    this doesn't change behaviour for a tenant that hasn't opted any user
    into routing -- exactly today's single-number dial.
    """
    numbers = get_eligible_agent_numbers(db, tenant.id)
    if not numbers:
        return [fallback_number] if fallback_number else []

    strategy = tenant.ivr_routing_strategy or STRATEGY_SINGLE
    if strategy == STRATEGY_PARALLEL:
        return numbers
    if strategy == STRATEGY_ROUND_ROBIN:
        return [_round_robin_pick(tenant.id, numbers)]
    return [numbers[0]]


def resolve_greeting_url(tenant: Tenant, expires_in: int = 300) -> str | None:
    """Presigned URL for the client-uploaded greeting MP3, or None if no
    greeting is configured. Short expiry is fine and safer than a public
    bucket -- Vobiz fetches the URL immediately when it renders the answer
    XML, it doesn't hold onto it."""
    if not tenant.ivr_greeting_audio_key:
        return None
    return media_storage.get_presigned_media_url(tenant.ivr_greeting_audio_key, expires_in=expires_in)
