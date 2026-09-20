"""Tenant handoff settings: the number/link the bot gives a guest who asks
for a human. Per CLAUDE.md every endpoint gets happy path + wrong role."""
import uuid

from app.core.security import create_access_token, get_password_hash
from app.models.tenant import Tenant
from app.models.user import User, UserRole

PHONE = "+918071581336"
WA = "https://wa.me/message/GJURLNEARL2SE1"


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="HO", slug=f"ho-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush(); return t


def _user(db, tenant_id, role=UserRole.OWNER):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name="U",
        email=f"u-{uuid.uuid4().hex[:6]}@t.com",
        hashed_password=get_password_hash("pw"), role=role, is_active=True,
    )
    db.add(u); db.flush(); return u


def _auth(u):
    return {"Authorization": "Bearer " + create_access_token(
        {"sub": u.id, "tenant_id": u.tenant_id, "role": u.role.value})}


def test_owner_can_save_and_read_back(client, db):
    t = _tenant(db); owner = _user(db, t.id, UserRole.OWNER); db.commit()

    res = client.patch("/api/v1/tenants/me/handoff", headers=_auth(owner), json={
        "handoff_phone": PHONE, "handoff_whatsapp_url": WA, "handoff_enabled": True,
    })
    assert res.status_code == 200, res.text
    assert res.json()["handoff_phone"] == PHONE

    res = client.get("/api/v1/tenants/me/handoff", headers=_auth(owner))
    assert res.json()["handoff_whatsapp_url"] == WA


def test_concierge_role_cannot_change_it(client, db):
    """An agent must not be able to redirect leads to another number."""
    t = _tenant(db); agent = _user(db, t.id, UserRole.CONCIERGE); db.commit()
    res = client.patch("/api/v1/tenants/me/handoff", headers=_auth(agent),
                       json={"handoff_phone": PHONE})
    assert res.status_code == 403


def test_undialable_phone_is_rejected(client, db):
    """Guests are told to dial this -- a broken number loses the lead."""
    t = _tenant(db); owner = _user(db, t.id); db.commit()
    res = client.patch("/api/v1/tenants/me/handoff", headers=_auth(owner),
                       json={"handoff_phone": "call us maybe"})
    assert res.status_code == 422


def test_non_https_whatsapp_link_is_rejected(client, db):
    t = _tenant(db); owner = _user(db, t.id); db.commit()
    res = client.patch("/api/v1/tenants/me/handoff", headers=_auth(owner),
                       json={"handoff_whatsapp_url": "wa.me/123"})
    assert res.status_code == 422


def test_blank_values_clear_the_setting(client, db):
    t = _tenant(db); owner = _user(db, t.id); db.commit()
    client.patch("/api/v1/tenants/me/handoff", headers=_auth(owner),
                 json={"handoff_phone": PHONE})
    res = client.patch("/api/v1/tenants/me/handoff", headers=_auth(owner),
                       json={"handoff_phone": "  "})
    assert res.status_code == 200
    assert res.json()["handoff_phone"] is None


def test_can_be_disabled_while_keeping_the_details(client, db):
    """Staging the details before letting the bot volunteer them."""
    t = _tenant(db); owner = _user(db, t.id); db.commit()
    res = client.patch("/api/v1/tenants/me/handoff", headers=_auth(owner), json={
        "handoff_phone": PHONE, "handoff_whatsapp_url": WA, "handoff_enabled": False,
    })
    assert res.json()["handoff_enabled"] is False
    assert res.json()["handoff_phone"] == PHONE
