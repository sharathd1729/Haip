"""Autonomous-send rate limit tests.

The scenario these exist to prevent: the AI replying to a guest over and
over with no human noticing.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.conversation import Conversation, Message, ChannelType
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.services import ai_rate_limit_service as rl


def _mk(db, *, per_conv=6, consecutive=3, per_tenant=60):
    t = Tenant(
        name="RL", slug=f"rl-{uuid.uuid4().hex[:8]}",
        ai_max_sends_per_conversation_hour=per_conv,
        ai_max_consecutive_replies=consecutive,
        ai_max_sends_per_tenant_hour=per_tenant,
    )
    db.add(t); db.flush()
    g = Guest(tenant_id=t.id, name="Arjun")
    db.add(g); db.flush()
    c = Conversation(tenant_id=t.id, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True, ai_mode="autonomous")
    db.add(c); db.commit()
    return t, g, c


def _msg(db, conv, tenant, *, direction, autonomous=False, minutes_ago=0):
    m = Message(
        tenant_id=tenant.id, conversation_id=conv.id,
        direction=direction, channel=ChannelType.WHATSAPP,
        body="x", is_ai_generated=(direction == "outbound"),
        sent_autonomously=autonomous,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )
    db.add(m); db.commit()
    return m


# ─── baseline ────────────────────────────────────────────────────────────────

def test_allows_send_on_a_fresh_conversation(db):
    t, g, c = _mk(db)
    allowed, reason = rl.check_send_allowed(db, t, c)
    assert allowed is True and reason is None


def test_null_conversation_is_allowed(db):
    t, g, c = _mk(db)
    assert rl.check_send_allowed(db, t, None)[0] is True


# ─── consecutive-reply loop guard ────────────────────────────────────────────

def test_blocks_after_consecutive_ai_replies_without_guest_response(db):
    """The core loop signal -- a real exchange alternates."""
    t, g, c = _mk(db, consecutive=3)
    for _ in range(3):
        _msg(db, c, t, direction="outbound", autonomous=True)
    allowed, reason = rl.check_send_allowed(db, t, c)
    assert allowed is False
    assert "consecutive" in reason


def test_guest_reply_resets_the_consecutive_counter(db):
    t, g, c = _mk(db, consecutive=3)
    # Spaced timestamps: the loop guard orders by created_at, and back-to-back datetime.now() calls can tie on a coarse
    # clock (Windows), which made the guest's reply sort before the AI messages and this test fail intermittently.
    for minutes_ago in (4, 3, 2):
        _msg(db, c, t, direction="outbound", autonomous=True, minutes_ago=minutes_ago)
    _msg(db, c, t, direction="inbound", minutes_ago=1)
    allowed, _ = rl.check_send_allowed(db, t, c)
    assert allowed is True


def test_human_sent_replies_do_not_count_toward_the_loop_guard(db):
    """An agent replying three times is not the AI looping."""
    t, g, c = _mk(db, consecutive=3)
    for _ in range(3):
        _msg(db, c, t, direction="outbound", autonomous=False)
    assert rl.check_send_allowed(db, t, c)[0] is True


# ─── per-conversation hourly cap ─────────────────────────────────────────────

def test_blocks_when_conversation_hourly_cap_reached(db):
    t, g, c = _mk(db, per_conv=3, consecutive=99)
    for _ in range(3):
        _msg(db, c, t, direction="outbound", autonomous=True)
        _msg(db, c, t, direction="inbound")  # keep consecutive guard clear
    allowed, reason = rl.check_send_allowed(db, t, c)
    assert allowed is False
    assert "last hour" in reason


def test_sends_older_than_an_hour_do_not_count(db):
    t, g, c = _mk(db, per_conv=3, consecutive=99)
    for _ in range(5):
        _msg(db, c, t, direction="outbound", autonomous=True, minutes_ago=90)
    assert rl.check_send_allowed(db, t, c)[0] is True


# ─── tenant-wide cap ─────────────────────────────────────────────────────────

def test_tenant_wide_cap_catches_fan_out_across_conversations(db):
    """No single conversation looks abnormal, but the workspace is blasting."""
    t, g, c = _mk(db, per_conv=99, consecutive=99, per_tenant=5)
    for i in range(5):
        # a fan-out is many guests' conversations; one open conversation per guest+channel is a database rule
        other_guest = Guest(tenant_id=t.id, name=f"Fan-out guest {i}")
        db.add(other_guest); db.flush()
        other = Conversation(tenant_id=t.id, guest_id=other_guest.id, channel=ChannelType.WHATSAPP, is_open=True)
        db.add(other); db.commit()
        _msg(db, other, t, direction="outbound", autonomous=True)
    allowed, reason = rl.check_send_allowed(db, t, c)
    assert allowed is False
    assert "workspace" in reason


def test_other_tenants_sends_do_not_count(db):
    t1, g1, c1 = _mk(db, per_tenant=2, consecutive=99, per_conv=99)
    t2, g2, c2 = _mk(db, per_tenant=2, consecutive=99, per_conv=99)
    for _ in range(3):
        _msg(db, c2, t2, direction="outbound", autonomous=True)
    assert rl.check_send_allowed(db, t1, c1)[0] is True


# ─── limit configuration ─────────────────────────────────────────────────────

def test_zero_or_negative_limits_fall_back_to_defaults(db):
    """A 0 would disable autonomous sending by the back door; the kill
    switch is the visible way to do that."""
    t, g, c = _mk(db, per_conv=0, consecutive=0, per_tenant=0)
    assert rl.check_send_allowed(db, t, c)[0] is True


def test_missing_tenant_uses_defaults(db):
    t, g, c = _mk(db)
    assert rl.check_send_allowed(db, None, c)[0] is True
