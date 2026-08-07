"""Regression: GET /dashboard's calls_this_week / avg_qa_score / total_calls
counted calls from a disconnected IVR provider (e.g. Mcube, replaced by
Vobiz for Ratha) months after the disconnect -- calls.py's list/detail
endpoints already filtered these out (test_click_to_call_and_provider_
filter.py), but the dashboard summary endpoint never matched that filter."""
import os
import uuid
from datetime import datetime, timezone
import pytest

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.call import Call, CallDirection
from app.api.v1.endpoints.dashboard import get_dashboard

# get_dashboard() always computes chat_response_p95_seconds via a
# Postgres-only percentile_cont() query -- skip under the default local
# SQLite test run, same as test_dashboard_stage_fix.py; CI's Postgres
# testcontainer runs these for real.
pytestmark = pytest.mark.skipif(
    "sqlite" in os.environ.get("DATABASE_URL", "sqlite"),
    reason="requires Postgres (percentile_cont)",
)


def _make_tenant(db, ivr_provider=None):
    t = Tenant(id=str(uuid.uuid4()), name="TenantDash", slug=f"dash-{uuid.uuid4().hex[:6]}",
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


def _make_call(db, tenant_id, ivr_provider, ai_score=None):
    call = Call(
        id=str(uuid.uuid4()), tenant_id=tenant_id, ivr_provider=ivr_provider,
        ivr_call_id=str(uuid.uuid4()), direction=CallDirection.INBOUND,
        from_number="+919876543210", to_number="+912271264296", duration_seconds=30,
        ai_score=ai_score, ai_score_status="done" if ai_score is not None else None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(call)
    db.commit()
    return call


def test_dashboard_excludes_disconnected_provider_calls_from_counts(db):
    tenant = _make_tenant(db, ivr_provider="vobiz")
    user = _make_user(db, tenant.id)
    _make_call(db, tenant.id, "vobiz", ai_score=90)
    _make_call(db, tenant.id, "mcube", ai_score=10)
    db.commit()

    result = get_dashboard(db=db, current_user=user)

    assert result["total_calls"] == 1
    assert result["calls_this_week"] == 1
    assert result["avg_qa_score"] == 90.0
    assert len(result["recent_calls"]) == 1


def test_dashboard_shows_everything_when_no_active_provider_set(db):
    tenant = _make_tenant(db, ivr_provider=None)
    user = _make_user(db, tenant.id)
    _make_call(db, tenant.id, "vobiz", ai_score=90)
    _make_call(db, tenant.id, "mcube", ai_score=10)
    db.commit()

    result = get_dashboard(db=db, current_user=user)

    assert result["total_calls"] == 2
    assert result["calls_this_week"] == 2
