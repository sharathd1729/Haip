"""POST /api/v1/analytics/ask/freeform -- Owner-only Phase 2 soft launch role gate."""
import uuid

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.core.security import create_access_token, get_password_hash


def _make_tenant(db, name="T"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"slug-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush(); return t


def _make_user(db, tenant_id, role=UserRole.OWNER):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id,
        name="Test User", email=f"u-{uuid.uuid4().hex[:6]}@test.com",
        hashed_password=get_password_hash("pw"), role=role, is_active=True,
    )
    db.add(u); db.flush(); return u


def _token(user):
    return create_access_token({"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value})


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_freeform_forbidden_for_non_owner_roles(client, db):
    tenant = _make_tenant(db)
    for role in (UserRole.MANAGER, UserRole.RESERVATIONS, UserRole.CONCIERGE, UserRole.READ_ONLY):
        user = _make_user(db, tenant.id, role)
        db.commit()
        resp = client.post(
            "/api/v1/analytics/ask/freeform",
            json={"question": "how many inquiries this month"},
            headers=_auth(_token(user)),
        )
        assert resp.status_code == 403, f"role {role} should be forbidden, got {resp.status_code}"


def test_freeform_rejects_empty_question(client, db):
    tenant = _make_tenant(db)
    user = _make_user(db, tenant.id, UserRole.OWNER)
    db.commit()

    resp = client.post(
        "/api/v1/analytics/ask/freeform",
        json={"question": "   "},
        headers=_auth(_token(user)),
    )
    assert resp.status_code == 422
