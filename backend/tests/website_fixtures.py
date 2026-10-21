"""Shared helpers for the website builder tests (not a test module)."""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models.module import Module, WorkspaceModule
from app.models.property import Property
from app.models.tenant import Tenant
from app.models.user import UserRole
from tests.conftest import seed_capabilities
from tests.test_marketing_studio_content import make_user

BASE = "/api/v1/websites"


def enable(db, tenant_id, code="website"):
    mod = db.query(Module).filter_by(code=code).first()
    if mod is None:
        mod = Module(id=str(uuid.uuid4()), code=code, name=code)
        db.add(mod)
        db.flush()
    db.add(WorkspaceModule(id=str(uuid.uuid4()), workspace_id=tenant_id, module_id=mod.id, enabled=True))
    db.commit()


def add_property(db, tenant_id, name="Green Goose", price=4200, **kw):
    p = Property(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, slug=name.lower().replace(" ", "-"),
                 type=kw.pop("type", "villa"), is_active=True, max_adults=kw.pop("max_adults", 4),
                 max_children=kw.pop("max_children", 0), price_per_day=Decimal(str(price)) if price is not None else None,
                 city=kw.pop("city", "Coorg"), description=kw.pop("description", "A quiet villa in the coffee hills."), **kw)
    db.add(p)
    db.commit()
    return p


def make_tenant(db, name="Other"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"{name.lower()}-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.commit()
    seed_capabilities(db, t.id)
    enable(db, t.id)
    return t


@pytest.fixture()
def wsite(db, client, tenant_and_user):
    """A workspace with the website module, a property, an owner/manager/marketing/foh user and a created site."""
    tenant = tenant_and_user["tenant"]
    tenant.brand_config = {"business_profile": {"tagline": "Quiet villas in the coffee hills", "contact_phone": "+919876543210",
                                                "description": "Two private pool villas near Madikeri, Coorg, with a cook on call."}}
    db.commit()
    seed_capabilities(db, tenant.id)
    enable(db, tenant.id)
    owner_h = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    manager, manager_h = make_user(db, tenant.id, UserRole.MANAGER)
    manager2, manager2_h = make_user(db, tenant.id, UserRole.MANAGER)
    mkt, mkt_h = make_user(db, tenant.id, UserRole.MARKETING)
    foh, foh_h = make_user(db, tenant.id, UserRole.FOH)
    prop = add_property(db, tenant.id)
    r = client.post(f"{BASE}/site", json={}, headers=owner_h)
    assert r.status_code == 201, r.text
    return {"tenant": tenant, "owner": tenant_and_user["user"], "owner_h": owner_h, "manager": manager,
            "manager_h": manager_h, "manager2_h": manager2_h, "mkt": mkt, "mkt_h": mkt_h, "foh_h": foh_h,
            "prop": prop, "site": r.json()}


def draft(client, headers):
    r = client.get(f"{BASE}/draft", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def save(client, headers, doc, sha):
    return client.put(f"{BASE}/draft", json={"doc": doc, "base_sha256": sha}, headers=headers)


def publish_live(client, wsite):
    d = draft(client, wsite["owner_h"])
    r = client.post(f"{BASE}/versions/{d['version']['id']}/publish", json={"version_id": d["version"]["id"]}, headers=wsite["owner_h"])
    assert r.status_code == 200, r.text
    return r.json()


def host_of(wsite) -> str:
    return wsite["site"]["url"].split("://", 1)[1]


def future(days: int):
    from datetime import date
    return date.today() + timedelta(days=days)
