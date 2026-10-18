"""message_metrics.chat_response_by_agent_source: first human reply split by where the guest wrote.

Pinned: personal WhatsApp bridge (conversation source OR the message's own channel_metadata source) vs the Cloud number vs
Instagram; group chats and mirrored phone history are left out unless include_history; the per-source and overall totals come
from the same query; nothing answered = None (never 0 seconds); another workspace's messages never count.
PostgreSQL only (LATERAL, percentile_cont, GROUPING SETS, JSON ->>), like test_message_metrics_by_agent.py.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services.message_metrics import chat_response_by_agent_source

pytestmark = pytest.mark.skipif(
    "sqlite" in os.environ.get("DATABASE_URL", "sqlite"),
    reason="requires Postgres (LATERAL join, percentile_cont, GROUPING SETS)",
)

NOW = datetime.now(timezone.utc)


def _ids(tenant_and_user):
    t, u = tenant_and_user["tenant"], tenant_and_user["user"]
    return (t["id"] if isinstance(t, dict) else t.id), (u["id"] if isinstance(u, dict) else u.id)


def _conv(db, tid, channel=ChannelType.WHATSAPP, source=None):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Source Guest")
    db.add(g); db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=channel, source=source, is_open=True)
    db.add(c); db.flush()
    return c


def _pair(db, tid, conv, agent_id, minutes_ago, gap_minutes, meta=None, reply_meta=None):
    """A guest message and, gap_minutes later, the agent's reply."""
    at = NOW - timedelta(minutes=minutes_ago)
    ch = "instagram" if conv.channel == ChannelType.INSTAGRAM else "whatsapp"
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.INBOUND, channel=ch,
                   body="hi", created_at=at, channel_metadata=meta))
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.OUTBOUND, channel=ch,
                   body="hello", sender_id=agent_id, created_at=at + timedelta(minutes=gap_minutes),
                   channel_metadata=reply_meta if reply_meta is not None else meta))


def test_splits_by_source_and_totals(db, tenant_and_user):
    tid, agent = _ids(tenant_and_user)
    bridge = _conv(db, tid, source="personal_bridge")
    _pair(db, tid, bridge, agent, 300, 10, meta={"source": "personal_bridge", "chat_type": "user"})
    cloud = _conv(db, tid)
    _pair(db, tid, cloud, agent, 280, 2)
    # a bridged message that landed in the guest's open Cloud thread still counts as personal WhatsApp
    _pair(db, tid, cloud, agent, 200, 20, meta={"source": "personal_bridge", "chat_type": "user"})
    ig = _conv(db, tid, channel=ChannelType.INSTAGRAM)
    _pair(db, tid, ig, agent, 100, 4)
    db.commit()

    out = chat_response_by_agent_source(db, tid, NOW - timedelta(days=1))
    assert out["by_source"]["personal_whatsapp"]["response_count"] == 2
    assert out["by_source"]["personal_whatsapp"]["avg_seconds"] == pytest.approx(15 * 60)
    assert out["by_source"]["whatsapp_cloud"]["avg_seconds"] == pytest.approx(120)
    assert out["by_source"]["instagram"]["avg_seconds"] == pytest.approx(240)
    assert out["all"]["response_count"] == 4
    assert out["all"]["avg_seconds"] == pytest.approx((600 + 120 + 1200 + 240) / 4)
    assert {(r["agent_id"], r["source"]) for r in out["by_agent"]} == {
        (agent, "personal_whatsapp"), (agent, "whatsapp_cloud"), (agent, "instagram")}


def test_groups_and_history_are_left_out_unless_history_is_asked_for(db, tenant_and_user):
    tid, agent = _ids(tenant_and_user)
    group = _conv(db, tid, source="personal_bridge")
    _pair(db, tid, group, agent, 300, 1, meta={"source": "personal_bridge", "chat_type": "group"})
    old = _conv(db, tid, source="personal_bridge")
    _pair(db, tid, old, agent, 200, 30, meta={"source": "personal_bridge", "chat_type": "user", "history": True})
    db.commit()

    live = chat_response_by_agent_source(db, tid, NOW - timedelta(days=1))
    assert live["all"] is None and live["by_agent"] == []
    assert live["by_source"] == {"personal_whatsapp": None, "whatsapp_cloud": None, "instagram": None}

    with_history = chat_response_by_agent_source(db, tid, NOW - timedelta(days=1), include_history=True)
    assert with_history["by_source"]["personal_whatsapp"]["response_count"] == 1          # the group chat is still out
    assert with_history["by_source"]["personal_whatsapp"]["avg_seconds"] == pytest.approx(1800)


def test_a_mirrored_history_reply_is_not_a_reply_to_a_live_message(db, tenant_and_user):
    tid, agent = _ids(tenant_and_user)
    c = _conv(db, tid, source="personal_bridge")
    _pair(db, tid, c, agent, 300, 5, meta={"source": "personal_bridge", "chat_type": "user"},
          reply_meta={"source": "personal_bridge", "chat_type": "user", "history": True})
    db.commit()
    assert chat_response_by_agent_source(db, tid, NOW - timedelta(days=1))["all"] is None


def test_another_workspace_never_counts(db, tenant_and_user):
    tid, agent = _ids(tenant_and_user)
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other); db.flush()
    stranger = User(id=str(uuid.uuid4()), tenant_id=other.id, name="X", email=f"x-{uuid.uuid4().hex[:6]}@t.com",
                    hashed_password="x", role=UserRole.OWNER, is_active=True)
    db.add(stranger); db.flush()
    _pair(db, other.id, _conv(db, other.id), stranger.id, 100, 3)
    _pair(db, tid, _conv(db, tid), agent, 100, 7)
    db.commit()
    mine = chat_response_by_agent_source(db, tid, NOW - timedelta(days=1))
    assert mine["all"]["response_count"] == 1 and mine["all"]["avg_seconds"] == pytest.approx(420)
    assert all(r["agent_id"] == agent for r in mine["by_agent"])
