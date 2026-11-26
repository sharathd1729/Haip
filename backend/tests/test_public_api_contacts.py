"""Public API contacts: scopes, paging, upsert by phone (never re-opts in), tags/lists update, opt out, isolation."""
import uuid

from app.api.v1.endpoints.messaging import WASubscriber
from app.models.audit_event import AuditEvent
from app.models.tenant import Tenant
from app.services import wa_contacts
from tests.test_public_api import BASE, _h, _key, pub  # noqa: F401 -- pub is a fixture

R, W = ["contacts:read"], ["contacts:read", "contacts:write"]


def _other(db):
    t = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.commit()
    return t.id


def test_scopes(pub, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    none = _h(_key(db, tid, ["bookings:read"]))
    read = _h(_key(db, tid, R))
    assert pub.get(f"{BASE}/contacts", headers=none).json()["error"]["code"] == "insufficient_scope"
    assert pub.get(f"{BASE}/contacts", headers=read).status_code == 200
    r = pub.post(f"{BASE}/contacts", json={"phone": "+919876500001"}, headers=read)
    assert r.status_code == 403 and r.json()["error"]["code"] == "insufficient_scope"


def test_upsert_page_get_patch(pub, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    h = _h(_key(db, tid, W))
    lst = wa_contacts.create_list(db, tid, "Corporate HR contacts", None)
    db.commit()
    r = pub.post(f"{BASE}/contacts", json={"phone": "98765 00001", "name": "Asha", "tags": ["vip"], "list_ids": [lst.id]},
                 headers=h)
    assert r.status_code == 201
    c = r.json()["data"]
    assert c["phone"] == "+919876500001" and c["opted_in"] and c["tags"] == ["vip"] and c["list_ids"] == [lst.id]

    r = pub.post(f"{BASE}/contacts", json={"phone": "+919876500001", "tags": ["wedding"]}, headers=h)
    assert r.status_code == 200 and r.json()["data"]["tags"] == ["vip", "wedding"]
    assert pub.post(f"{BASE}/contacts", json={"phone": "12"}, headers=h).json()["error"]["code"] == "invalid_phone"
    assert pub.post(f"{BASE}/contacts", json={"phone": "+919876500002", "list_ids": ["nope"]}, headers=h).status_code == 422

    for i in range(3, 6):
        pub.post(f"{BASE}/contacts", json={"phone": f"+91987650000{i}"}, headers=h)
    page = pub.get(f"{BASE}/contacts?per_page=2&page=2", headers=h).json()
    assert page["meta"] == {"page": 2, "per_page": 2, "total": 4, "total_pages": 2} and len(page["data"]) == 2
    assert pub.get(f"{BASE}/contacts?list_id={lst.id}", headers=h).json()["meta"]["total"] == 1
    assert pub.get(f"{BASE}/contact-lists", headers=h).json()["data"] == [{"id": lst.id, "name": "Corporate HR contacts", "count": 1}]

    r = pub.patch(f"{BASE}/contacts/{c['id']}", json={"name": "Asha Rao", "remove_tags": ["vip"], "remove_list_ids": [lst.id]},
                  headers=h)
    assert r.json()["data"]["name"] == "Asha Rao" and r.json()["data"]["tags"] == ["wedding"] and r.json()["data"]["list_ids"] == []
    assert pub.get(f"{BASE}/contacts/{c['id']}", headers=h).json()["data"]["name"] == "Asha Rao"


def test_opt_out_is_audited_and_upsert_never_re_opts_in(pub, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    h = _h(_key(db, tid, W))
    cid = pub.post(f"{BASE}/contacts", json={"phone": "+919876500001"}, headers=h).json()["data"]["id"]
    assert pub.post(f"{BASE}/contacts/{cid}/opt-out", headers=h).json()["data"]["opted_in"] is False
    ev = db.query(AuditEvent).filter_by(tenant_id=tid, action="subscribers.opt_out").one()
    assert ev.actor_user_id is None and ev.payload["actor"].startswith("api_key:")
    r = pub.post(f"{BASE}/contacts", json={"phone": "+919876500001", "tags": ["again"]}, headers=h)
    assert r.status_code == 200 and r.json()["data"]["opted_in"] is False and r.json()["data"]["tags"] == ["again"]


def test_other_accounts_contacts_are_invisible(pub, db, tenant_and_user):
    tid, other = tenant_and_user["tenant"].id, _other(db)
    theirs = WASubscriber(id=str(uuid.uuid4()), tenant_id=other, phone="+919876500009", opted_in=True, tags=[], list_ids=[])
    db.add(theirs)
    their_list = wa_contacts.create_list(db, other, "Theirs", None)
    db.commit()
    h = _h(_key(db, tid, W))
    assert pub.get(f"{BASE}/contacts", headers=h).json()["meta"]["total"] == 0
    assert pub.get(f"{BASE}/contacts/{theirs.id}", headers=h).status_code == 404
    assert pub.patch(f"{BASE}/contacts/{theirs.id}", json={"name": "x"}, headers=h).status_code == 404
    assert pub.post(f"{BASE}/contacts/{theirs.id}/opt-out", headers=h).status_code == 404
    r = pub.post(f"{BASE}/contacts", json={"phone": "+919876500009", "list_ids": [their_list.id]}, headers=h)
    assert r.json()["error"]["code"] == "unknown_list"
    db.refresh(theirs)
    assert theirs.opted_in is True
