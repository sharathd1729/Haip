"""IVR call routing tests.

The scenario these exist to prevent: shipping the agent-pool routing and
silently changing behaviour for every tenant that hasn't opted anyone in
yet -- resolve_dial_numbers must fall back to today's single forward_number
exactly when no eligible agent is configured.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import ivr_routing_service as ivr

# TimestampMixin's created_at is set client-side (datetime.now()), so two
# users created back-to-back in a fast test can land on the exact same
# timestamp -- the created_at tiebreak then falls through to id (a random
# UUID), making order flaky. Assigning explicit, strictly increasing
# timestamps here tests the real ordering behaviour without that flakiness.
_next_offset = itertools.count()


def _tenant(db, **kw):
    t = Tenant(name="IVR", slug=f"ivr-{uuid.uuid4().hex[:8]}", **kw)
    db.add(t); db.commit()
    return t


def _user(db, tenant, *, phone="+919876500001", enabled=True, active=True, deleted=False):
    u = User(
        tenant_id=tenant.id, email=f"{uuid.uuid4().hex[:8]}@x.com", name="Agent",
        role=UserRole.CONCIERGE, phone=phone,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=next(_next_offset)),
        ivr_call_routing_enabled=enabled, is_active=active, is_deleted=deleted,
    )
    db.add(u); db.commit()
    return u


# ─── get_eligible_agent_numbers ────────────────────────────────────────────────

def test_excludes_users_not_opted_in(db):
    t = _tenant(db)
    _user(db, t, phone="+911", enabled=False)
    assert ivr.get_eligible_agent_numbers(db, t.id) == []


def test_excludes_inactive_and_deleted_users(db):
    t = _tenant(db)
    _user(db, t, phone="+911", active=False)
    _user(db, t, phone="+912", deleted=True)
    assert ivr.get_eligible_agent_numbers(db, t.id) == []


def test_excludes_users_with_no_phone(db):
    t = _tenant(db)
    _user(db, t, phone=None)
    _user(db, t, phone="")
    assert ivr.get_eligible_agent_numbers(db, t.id) == []


def test_includes_eligible_users_in_created_order(db):
    t = _tenant(db)
    _user(db, t, phone="+911")
    _user(db, t, phone="+912")
    assert ivr.get_eligible_agent_numbers(db, t.id) == ["+911", "+912"]


def test_scoped_to_own_tenant(db):
    t1 = _tenant(db)
    t2 = _tenant(db)
    _user(db, t1, phone="+911")
    _user(db, t2, phone="+912")
    assert ivr.get_eligible_agent_numbers(db, t1.id) == ["+911"]


# ─── resolve_dial_numbers ───────────────────────────────────────────────────────

def test_no_eligible_agents_falls_back_to_forward_number(db):
    """The compatibility guarantee: a tenant that hasn't opted any user
    into routing yet must see no change from today's single-number dial."""
    t = _tenant(db, ivr_routing_strategy="parallel")
    assert ivr.resolve_dial_numbers(db, t, fallback_number="+91999") == ["+91999"]


def test_no_eligible_agents_and_no_fallback_returns_empty(db):
    t = _tenant(db)
    assert ivr.resolve_dial_numbers(db, t, fallback_number=None) == []


def test_single_strategy_dials_only_first_eligible_agent(db):
    t = _tenant(db, ivr_routing_strategy="single")
    _user(db, t, phone="+911")
    _user(db, t, phone="+912")
    assert ivr.resolve_dial_numbers(db, t, fallback_number="+91999") == ["+911"]


def test_parallel_strategy_dials_every_eligible_agent(db):
    t = _tenant(db, ivr_routing_strategy="parallel")
    _user(db, t, phone="+911")
    _user(db, t, phone="+912")
    _user(db, t, phone="+913")
    assert ivr.resolve_dial_numbers(db, t, fallback_number=None) == ["+911", "+912", "+913"]


def test_round_robin_rotates_across_calls(db):
    t = _tenant(db, ivr_routing_strategy="round_robin")
    _user(db, t, phone="+911")
    _user(db, t, phone="+912")
    _user(db, t, phone="+913")

    with patch("app.services.ivr_routing_service.cache.incr", side_effect=[1, 2, 3, 4]):
        picks = [ivr.resolve_dial_numbers(db, t, fallback_number=None)[0] for _ in range(4)]
    assert picks == ["+912", "+913", "+911", "+912"]


def test_round_robin_with_one_agent_always_picks_them_without_touching_cache(db):
    t = _tenant(db, ivr_routing_strategy="round_robin")
    _user(db, t, phone="+911")
    with patch("app.services.ivr_routing_service.cache.incr") as mock_incr:
        result = ivr.resolve_dial_numbers(db, t, fallback_number=None)
    assert result == ["+911"]
    mock_incr.assert_not_called()


def test_round_robin_degrades_to_first_agent_when_redis_unreachable(db):
    """cache.incr returns None on a Redis outage (fail-open convention) --
    must not raise, and must still pick a real, predictable agent."""
    t = _tenant(db, ivr_routing_strategy="round_robin")
    _user(db, t, phone="+911")
    _user(db, t, phone="+912")
    with patch("app.services.ivr_routing_service.cache.incr", return_value=None):
        assert ivr.resolve_dial_numbers(db, t, fallback_number=None) == ["+911"]


def test_unknown_strategy_falls_back_to_single_behaviour(db):
    t = _tenant(db, ivr_routing_strategy="something_invalid")
    _user(db, t, phone="+911")
    _user(db, t, phone="+912")
    assert ivr.resolve_dial_numbers(db, t, fallback_number=None) == ["+911"]


# ─── resolve_greeting_url ───────────────────────────────────────────────────────

def test_no_greeting_configured_returns_none(db):
    t = _tenant(db)
    assert ivr.resolve_greeting_url(t) is None


def test_greeting_configured_returns_presigned_url(db):
    t = _tenant(db, ivr_greeting_audio_key="tenant123/ivr/greeting.mp3")
    with patch(
        "app.services.ivr_routing_service.media_storage.get_presigned_media_url",
        return_value="https://s3.example.com/signed",
    ) as mock_presign:
        url = ivr.resolve_greeting_url(t)
    assert url == "https://s3.example.com/signed"
    mock_presign.assert_called_once_with("tenant123/ivr/greeting.mp3", expires_in=300)
