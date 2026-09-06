"""GET /users/lite -- name-only directory open to every role.

Added alongside the Leads360 visibility-scope fix: the "Assigned to" filter
dropdown (and Inbox's @mention) called GET /users, which is owner/manager
only -- every other role got a silent 403 and an empty list. /users/lite
exposes id+name only, safe for any authenticated role.
"""
import uuid

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.core.security import create_access_token, get_password_hash


def _make_tenant(db, name="T"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"slug-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush(); return t


def _make_user(db, tenant_id, role=UserRole.OWNER, name="Test User"):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id,
        name=name, email=f"u-{uuid.uuid4().hex[:6]}@test.com",
        hashed_password=get_password_hash("pw"), role=role, is_active=True,
    )
    db.add(u); db.flush(); return u


def _auth(user):
    token = create_access_token({"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value})
    return {"Authorization": f"Bearer {token}"}


def test_concierge_can_list_users_lite(client, db):
    tenant = _make_tenant(db)
    agent = _make_user(db, tenant.id, UserRole.CONCIERGE, name="Jishant")
    other = _make_user(db, tenant.id, UserRole.CONCIERGE, name="Krisha")
    db.commit()

    resp = client.get("/api/v1/users/lite", headers=_auth(agent))
    assert resp.status_code == 200
    names = {row["name"] for row in resp.json()}
    assert {"Jishant", "Krisha"} <= names


def test_users_lite_excludes_sensitive_fields(client, db):
    tenant = _make_tenant(db)
    agent = _make_user(db, tenant.id, UserRole.CONCIERGE)
    db.commit()

    resp = client.get("/api/v1/users/lite", headers=_auth(agent))
    row = resp.json()[0]
    assert set(row.keys()) == {"id", "name"}


def test_users_lite_is_tenant_scoped(client, db):
    tenant_a = _make_tenant(db, "A")
    tenant_b = _make_tenant(db, "B")
    agent_a = _make_user(db, tenant_a.id, UserRole.CONCIERGE, name="OnlyInA")
    _make_user(db, tenant_b.id, UserRole.CONCIERGE, name="OnlyInB")
    db.commit()

    resp = client.get("/api/v1/users/lite", headers=_auth(agent_a))
    names = {row["name"] for row in resp.json()}
    assert names == {"OnlyInA"}
