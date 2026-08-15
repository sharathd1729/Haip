"""Tests for the role-aware dashboard rebuild's per-agent scorecard
(claude-fable-5-lovely-biscuit.md #5): agent_analytics_service.
get_agent_scorecard_rows().

Transitively calls message_metrics.chat_response_by_agent() (LATERAL join +
percentile_cont) -- same Postgres-only pattern as
test_message_metrics_by_agent.py, skip under local SQLite, CI's Postgres
testcontainer runs these for real.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.models.call import Call, CallDirection
from app.models.task import Task
from app.models.ai_draft_outcome import AIDraftOutcome
from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
from app.services.agent_analytics_service import get_agent_scorecard_rows

pytestmark = pytest.mark.skipif(
    "sqlite" in os.environ.get("DATABASE_URL", "sqlite"),
    reason="requires Postgres (LATERAL join, percentile_cont via chat_response_by_agent)",
)


def _ids(tenant_and_user):
    t, u = tenant_and_user["tenant"], tenant_and_user["user"]
    return (
        t["id"] if isinstance(t, dict) else t.id,
        u["id"] if isinstance(u, dict) else u.id,
    )


def _today_range():
    today = datetime.now(timezone.utc).date().isoformat()
    return today, today


def test_combines_every_phase_25_signal_for_one_agent(db, tenant_and_user):
    tenant_id, agent_id = _ids(tenant_and_user)
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="G", phone=f"+9199990{uuid.uuid4().hex[:5]}")
    db.add(guest); db.flush()

    stage = PipelineStage(id=str(uuid.uuid4()), tenant_id=tenant_id, key="active", label="Active", order=1)
    db.add(stage); db.flush()

    inquiry = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, stage_id=stage.id, assigned_to=agent_id)
    db.add(inquiry)

    task = Task(id=str(uuid.uuid4()), tenant_id=tenant_id, title="Follow up", assigned_to=agent_id, is_done=True)
    db.add(task)

    call = Call(
        id=str(uuid.uuid4()), tenant_id=tenant_id, agent_id=agent_id,
        ivr_provider="vobiz", ivr_call_id=str(uuid.uuid4()),
        direction=CallDirection.INBOUND, from_number="+919999000001", to_number="+919999000002",
        duration_seconds=120,
    )
    db.add(call)

    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv); db.flush()
    draft_msg = Message(id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id, direction=MessageDirection.OUTBOUND, channel="whatsapp", body="hi")
    db.add(draft_msg); db.flush()
    outcome = AIDraftOutcome(id=str(uuid.uuid4()), tenant_id=tenant_id, draft_message_id=draft_msg.id, outcome="sent_verbatim", actor_user_id=agent_id)
    db.add(outcome)
    db.commit()

    d_from, d_to = _today_range()
    rows = get_agent_scorecard_rows(db, tenant_id, d_from, d_to)

    row = next(r for r in rows if r["agent_id"] == agent_id)
    assert row["leads_handled"] == 1
    assert row["followups_completed"] == 1
    assert row["calls_answered"] == 1
    assert row["ai_drafts_approved"] == 1


def test_missed_call_without_recovery_counts_as_unrecovered(db, tenant_and_user):
    tenant_id, agent_id = _ids(tenant_and_user)
    call = Call(
        id=str(uuid.uuid4()), tenant_id=tenant_id, agent_id=agent_id,
        ivr_provider="vobiz", ivr_call_id=str(uuid.uuid4()),
        direction=CallDirection.INBOUND, from_number="+919999000001", to_number="+919999000002",
        duration_seconds=0,
    )
    db.add(call)
    db.commit()

    d_from, d_to = _today_range()
    rows = get_agent_scorecard_rows(db, tenant_id, d_from, d_to)
    row = next(r for r in rows if r["agent_id"] == agent_id)
    assert row["calls_missed"] == 1
    assert row["calls_missed_recovered"] == 0


def test_tenant_isolation(db, tenant_and_user):
    from app.models.tenant import Tenant
    from app.models.user import User, UserRole
    from app.core.security import get_password_hash

    tenant_id, agent_id = _ids(tenant_and_user)
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="G", phone=f"+9199990{uuid.uuid4().hex[:5]}")
    db.add(guest); db.flush()
    stage = PipelineStage(id=str(uuid.uuid4()), tenant_id=tenant_id, key="active", label="Active", order=1)
    db.add(stage); db.flush()
    db.add(Inquiry(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, stage_id=stage.id, assigned_to=agent_id))
    db.commit()

    other_tenant = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other_tenant); db.flush()
    other_user = User(
        id=str(uuid.uuid4()), tenant_id=other_tenant.id, name="Other Agent",
        email=f"o-{uuid.uuid4().hex[:6]}@test.com", hashed_password=get_password_hash("pw"),
        role=UserRole.CONCIERGE, is_active=True,
    )
    db.add(other_user); db.commit()

    d_from, d_to = _today_range()
    rows = get_agent_scorecard_rows(db, other_tenant.id, d_from, d_to)
    assert len(rows) == 1
    assert rows[0]["agent_id"] == other_user.id
    assert rows[0]["leads_handled"] == 0
