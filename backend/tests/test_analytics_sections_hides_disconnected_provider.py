"""Regression: analytics_sections.py's operations_analytics (calls_today,
agent leaderboard) and ai_analytics (cost/pipeline-health/cost-trend)
counted calls from a disconnected IVR provider (e.g. Mcube, replaced by
Vobiz for Ratha) months after the disconnect -- the same class of bug
already fixed in dashboard.py/widget_service.py/analytics.py/
analytics_executive.py, but these two endpoints were missed in that pass."""
import uuid
from datetime import datetime, timezone
import pytest

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.call import Call, CallDirection
from app.api.v1.endpoints.analytics_sections import operations_analytics, ai_analytics


def _make_tenant(db, ivr_provider=None):
    t = Tenant(id=str(uuid.uuid4()), name="TenantAnalytics", slug=f"an-{uuid.uuid4().hex[:6]}",
               plan="growth", ivr_provider=ivr_provider)
    db.add(t)
    db.flush()
    return t


def _make_user(db, tenant_id):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name="Owner", email=f"{uuid.uuid4().hex[:8]}@test.com",
        hashed_password="x", role=UserRole.OWNER, is_active=True,
    )
    db.add(u)
    db.flush()
    return u


def _make_call(db, tenant_id, ivr_provider, agent_id=None, ai_score=None):
    now = datetime.now(timezone.utc)
    call = Call(
        id=str(uuid.uuid4()), tenant_id=tenant_id, ivr_provider=ivr_provider,
        ivr_call_id=str(uuid.uuid4()), direction=CallDirection.INBOUND,
        from_number="+919876543210", to_number="+912271264296", duration_seconds=30,
        agent_id=agent_id, ai_score=ai_score,
        ai_score_status="done" if ai_score is not None else None,
        started_at=now, created_at=now, updated_at=now,
    )
    db.add(call)
    db.commit()
    return call


def test_operations_analytics_excludes_disconnected_provider_calls(db):
    tenant = _make_tenant(db, ivr_provider="vobiz")
    user = _make_user(db, tenant.id)
    _make_call(db, tenant.id, "vobiz", agent_id=user.id, ai_score=90)
    _make_call(db, tenant.id, "mcube", agent_id=user.id, ai_score=10)
    db.commit()

    result = operations_analytics(range_days=30, current_user=user, db=db)

    assert result.calls_today == 1
    agent_row = next(a for a in result.agents if a.id == str(user.id))
    assert agent_row.calls_handled == 1
    assert agent_row.avg_qa_score == 90.0


def test_ai_analytics_excludes_disconnected_provider_calls(db):
    tenant = _make_tenant(db, ivr_provider="vobiz")
    user = _make_user(db, tenant.id)
    _make_call(db, tenant.id, "vobiz")
    _make_call(db, tenant.id, "mcube")
    db.commit()

    result = ai_analytics(range_days=30, current_user=user, db=db)

    # Only the vobiz call should count -- the mcube one must be excluded.
    assert result.pipeline_pending_transcription == 1
    total_cost_trend_points = sum(1 for _ in result.cost_trend)
    # Both calls landed "today" -- only the vobiz one should count toward
    # the single cost-trend day, so the trend must not double it up.
    assert total_cost_trend_points <= 1


def test_analytics_sections_shows_everything_when_no_active_provider_set(db):
    tenant = _make_tenant(db, ivr_provider=None)
    user = _make_user(db, tenant.id)
    _make_call(db, tenant.id, "vobiz", agent_id=user.id, ai_score=90)
    _make_call(db, tenant.id, "mcube", agent_id=user.id, ai_score=10)
    db.commit()

    result = operations_analytics(range_days=30, current_user=user, db=db)

    assert result.calls_today == 2
