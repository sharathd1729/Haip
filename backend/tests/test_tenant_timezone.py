"""Workspace timezone (PATCH /tenants/me): the settings form always sent it, but the schema had no such field, so it was dropped."""

from app.models.audit_event import AuditEvent
from app.models.user import UserRole
from tests.test_increment1_defect_specs import _h, _tenant, _user

URL = "/api/v1/tenants/me"


def test_owner_saves_the_timezone_and_it_is_audited(client, db):
    t = _tenant(db)
    owner = _user(db, t.id, UserRole.OWNER)
    res = client.patch(URL, json={"timezone": "Asia/Dubai"}, headers=_h(owner))
    assert res.status_code == 200, res.text
    assert res.json()["timezone"] == "Asia/Dubai"
    assert client.get(URL, headers=_h(owner)).json()["timezone"] == "Asia/Dubai"
    row = db.query(AuditEvent).filter_by(tenant_id=t.id, action="tenant.timezone_changed").one()
    assert row.payload["to"] == "Asia/Dubai"


def test_an_unknown_timezone_is_refused(client, db):
    t = _tenant(db)
    owner = _user(db, t.id, UserRole.OWNER)
    assert client.patch(URL, json={"timezone": "Mars/Olympus"}, headers=_h(owner)).status_code == 422
    db.refresh(t)
    assert t.timezone == "Asia/Kolkata"


def test_front_desk_cannot_change_it(client, db):
    t = _tenant(db)
    foh = _user(db, t.id, UserRole.FOH)
    assert client.patch(URL, json={"timezone": "Asia/Dubai"}, headers=_h(foh)).status_code == 403


def test_another_workspace_is_untouched(client, db):
    mine, other = _tenant(db), _tenant(db)
    owner = _user(db, mine.id, UserRole.OWNER)
    assert client.patch(URL, json={"timezone": "Asia/Singapore"}, headers=_h(owner)).status_code == 200
    db.refresh(other)
    assert other.timezone == "Asia/Kolkata"
