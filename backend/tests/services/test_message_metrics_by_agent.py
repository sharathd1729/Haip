"""Tests for Phase 2.5 agent-accountability instrumentation
(HAIP_Agent_Analytics_Dashboard_Plan_1.md #2.5.1):
message_metrics.chat_response_by_agent().

Uses a LATERAL join + percentile_cont(), same Postgres-only pattern as the
existing chat_response_p95_seconds/avg_seconds -- skip under the default
local SQLite test run; CI's Postgres testcontainer runs these for real.
"""
import os
import uuid
from datetime import datetime, timezone, timedelta

import pytest

from app.models.guest import Guest
from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
from app.services.message_metrics import chat_response_by_agent

pytestmark = pytest.mark.skipif(
    "sqlite" in os.environ.get("DATABASE_URL", "sqlite"),
    reason="requires Postgres (LATERAL join, percentile_cont)",
)


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _make_conversation(db, tenant_id):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Metrics Guest", phone="+919999044556")
    db.add(guest); db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv); db.commit()
    return conv


def _msg(db, tenant_id, conv_id, direction, created_at, sender_id=None):
    m = Message(
        id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv_id,
        direction=direction, channel="whatsapp", body="hi", sender_id=sender_id,
        created_at=created_at,
    )
    db.add(m)
    return m


def test_groups_response_time_by_the_agent_who_replied(db, tenant_and_user):
    tenant_id = _tenant_id(tenant_and_user)
    actor_id = tenant_and_user["user"]["id"] if isinstance(tenant_and_user["user"], dict) else tenant_and_user["user"].id
    conv = _make_conversation(db, tenant_id)
    now = datetime.now(timezone.utc)

    _msg(db, tenant_id, conv.id, MessageDirection.INBOUND, now - timedelta(minutes=10))
    _msg(db, tenant_id, conv.id, MessageDirection.OUTBOUND, now - timedelta(minutes=5), sender_id=actor_id)
    db.commit()

    since = now - timedelta(hours=1)
    rows = chat_response_by_agent(db, tenant_id, since)

    assert len(rows) == 1
    assert rows[0]["agent_id"] == actor_id
    assert rows[0]["response_count"] == 1
    assert rows[0]["avg_seconds"] > 0


def test_excludes_replies_with_no_sender_id(db, tenant_and_user):
    """A reply sent without a sender_id (e.g. legacy data, or an automated
    send never attributed to a user) shouldn't show up under a fake agent
    bucket -- it's excluded rather than grouped under None."""
    tenant_id = _tenant_id(tenant_and_user)
    conv = _make_conversation(db, tenant_id)
    now = datetime.now(timezone.utc)

    _msg(db, tenant_id, conv.id, MessageDirection.INBOUND, now - timedelta(minutes=10))
    _msg(db, tenant_id, conv.id, MessageDirection.OUTBOUND, now - timedelta(minutes=5), sender_id=None)
    db.commit()

    rows = chat_response_by_agent(db, tenant_id, now - timedelta(hours=1))
    assert rows == []
