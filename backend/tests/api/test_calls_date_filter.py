"""Tests for the optional date_preset/date_from/date_to filter added to
GET /calls (agent-attribution dashboard plan -- the Agent Profile page's
Calls tab needs to scope to a date range, which this endpoint never
supported before)."""
import uuid
from datetime import datetime, timezone

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.call import Call
from app.core.security import create_access_token, get_password_hash


def _make_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush(); return t


def _make_user(db, tenant_id):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name="Owner",
        email=f"{uuid.uuid4().hex[:8]}@test.com", hashed_password=get_password_hash("pw"),
        role=UserRole.OWNER, is_active=True,
    )
    db.add(u); db.flush(); return u


def _token(user):
    return create_access_token({"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value})


def _make_call(db, tenant_id, created_at):
    c = Call(
        id=str(uuid.uuid4()), tenant_id=tenant_id, ivr_provider="vobiz",
        ivr_call_id=str(uuid.uuid4()), direction="outbound",
        from_number="+919000000001", to_number="+919000000002",
        created_at=created_at,
    )
    db.add(c); db.flush(); return c


def test_date_filter_scopes_to_the_requested_day(client, db):
    tenant = _make_tenant(db)
    user = _make_user(db, tenant.id)
    _make_call(db, tenant.id, datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc))
    _make_call(db, tenant.id, datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc))
    db.commit()

    resp = client.get(
        "/api/v1/calls",
        params={"date_preset": "custom", "date_from": "2026-08-24", "date_to": "2026-08-24"},
        headers={"Authorization": f"Bearer {_token(user)}"},
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_no_date_params_returns_everything_unchanged(client, db):
    """Backward compat: the main Calls page never sends date params --
    omitting them must return the full unfiltered list, exactly as before."""
    tenant = _make_tenant(db)
    user = _make_user(db, tenant.id)
    _make_call(db, tenant.id, datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc))
    _make_call(db, tenant.id, datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc))
    db.commit()

    resp = client.get("/api/v1/calls", headers={"Authorization": f"Bearer {_token(user)}"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 2
