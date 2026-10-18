"""Operations API: happy paths, role checks (ops.read / ops.write / ops.manage) and cross-tenant isolation."""
from unittest.mock import patch

import pytest

from app.models.audit_event import AuditEvent
from app.models.ops import OpsItem
from app.models.user import UserRole
from tests.conftest import seed_capabilities
from tests.ops_helpers import prop, staff, tenant
from tests.test_increment1_defect_specs import _h, _user


@pytest.fixture()
def w(db):
    t = tenant(db)
    seed_capabilities(db, t.id)
    return type("W", (), {
        "t": t, "p": prop(db, t.id),
        "owner": _user(db, t.id, UserRole.OWNER), "mgr": _user(db, t.id, UserRole.MANAGER),
        "foh": _user(db, t.id, UserRole.FOH), "mkt": _user(db, t.id, UserRole.MARKETING),
    })()


@pytest.fixture(autouse=True)
def _no_celery():
    with patch("app.api.v1.endpoints.ops.queue_delivery") as q:
        yield q


def _staff_body(**over):
    body = {"name": "Ravi", "phone": "+91 98450 12345", "whatsapp_opt_in": True,
            "duties": [{"duty": "maintenance", "property_id": None}]}
    body.update(over)
    return body


def test_manager_creates_staff_and_it_is_audited(client, db, w):
    r = client.post("/api/v1/ops/staff", json=_staff_body(), headers=_h(w.mgr))
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["phone_e164"] == "+919845012345" and data["whatsapp_opt_in_at"] and data["duties"][0]["duty"] == "maintenance"
    db.flush()
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="ops.staff.created").count() == 1
    dup = client.post("/api/v1/ops/staff", json=_staff_body(name="Other"), headers=_h(w.mgr))
    assert dup.status_code == 409


def test_staff_writes_need_ops_manage(client, w):
    assert client.post("/api/v1/ops/staff", json=_staff_body(), headers=_h(w.foh)).status_code == 403
    assert client.get("/api/v1/ops/staff", headers=_h(w.foh)).status_code == 200          # foh can read
    assert client.get("/api/v1/ops/staff", headers=_h(w.mkt)).status_code == 403          # marketing cannot


def test_invalid_phone_is_rejected(client, w):
    assert client.post("/api/v1/ops/staff", json=_staff_body(phone="12345"), headers=_h(w.owner)).status_code == 422


def test_shift_creation_and_on_duty(client, db, w):
    s = staff(db, w.t.id, "Ravi", "maintenance")
    r = client.post("/api/v1/ops/shifts", headers=_h(w.owner), json={
        "staff_id": s.id, "duty": "maintenance", "weekdays": [0, 1, 2, 3, 4, 5, 6], "start": "00:00", "end": "24:00"})
    assert r.status_code == 201 and len(r.json()) == 7
    duty = client.get("/api/v1/ops/on-duty", params={"duty": "maintenance"}, headers=_h(w.foh)).json()
    assert duty["on_shift"][0]["name"] == "Ravi" and duty["first_alert_recipients"] == ["Ravi"] and not duty["roster_gap"]


def test_shift_for_other_tenants_staff_is_404(client, db, w):
    other = tenant(db)
    s = staff(db, other.id, "Theirs", "maintenance")
    r = client.post("/api/v1/ops/shifts", headers=_h(w.owner), json={
        "staff_id": s.id, "duty": "maintenance", "weekdays": [0], "start": "08:00", "end": "20:00"})
    assert r.status_code == 404


def test_create_item_queues_alerts_after_commit(client, db, w, _no_celery):
    s = staff(db, w.t.id, "Ravi", "maintenance")
    client.post("/api/v1/ops/shifts", headers=_h(w.owner), json={
        "staff_id": s.id, "duty": "maintenance", "weekdays": list(range(7)), "start": "00:00", "end": "24:00"})
    r = client.post("/api/v1/ops/items", headers=_h(w.foh), json={
        "title": "AC not working", "severity": "critical", "duty": "maintenance", "category": "ac", "property_id": w.p.id})
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["status"] == "open" and item["source"] == "staff"
    _no_celery.assert_called_once()
    detail = client.get(f"/api/v1/ops/items/{item['id']}", headers=_h(w.foh)).json()
    assert [e["event"] for e in detail["events"]][:2] == ["created", "alerted"] and detail["alerts"]


def test_item_lifecycle_and_roles(client, db, w):
    r = client.post("/api/v1/ops/items", headers=_h(w.mgr), json={"title": "Towels missing", "severity": "low",
                                                                  "duty": "housekeeping", "category": "amenity_missing"})
    item_id = r.json()["id"]
    assert client.post(f"/api/v1/ops/items/{item_id}/acknowledge", headers=_h(w.mkt)).status_code == 403
    assert client.post(f"/api/v1/ops/items/{item_id}/acknowledge", headers=_h(w.foh)).status_code == 200
    assert client.post(f"/api/v1/ops/items/{item_id}/acknowledge", headers=_h(w.foh)).status_code == 409
    assert client.post(f"/api/v1/ops/items/{item_id}/cancel", json={}, headers=_h(w.foh)).status_code == 403
    r = client.post(f"/api/v1/ops/items/{item_id}/resolve", json={"note": "Restocked"}, headers=_h(w.foh))
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    live = client.get("/api/v1/ops/items", headers=_h(w.foh)).json()
    assert item_id not in [i["id"] for i in live]


def test_items_are_tenant_isolated(client, db, w):
    other = tenant(db)
    seed_capabilities(db, other.id)
    intruder = _user(db, other.id, UserRole.OWNER)
    item_id = client.post("/api/v1/ops/items", headers=_h(w.owner), json={
        "title": "Leak", "severity": "high", "duty": "maintenance"}).json()["id"]
    assert client.get(f"/api/v1/ops/items/{item_id}", headers=_h(intruder)).status_code == 404
    assert client.post(f"/api/v1/ops/items/{item_id}/resolve", json={}, headers=_h(intruder)).status_code == 404
    assert client.get("/api/v1/ops/items", headers=_h(intruder)).json() == []
    r = client.post("/api/v1/ops/items", headers=_h(intruder), json={
        "title": "x", "severity": "low", "duty": "maintenance", "property_id": w.p.id})
    assert r.status_code == 422                                                         # someone else's property
    assert db.query(OpsItem).filter_by(tenant_id=other.id).count() == 0


def test_settings_and_template_install(client, db, w):
    r = client.get("/api/v1/ops/settings", headers=_h(w.foh))
    assert r.status_code == 200 and r.json()["template_status"]["ops_alert_v1"] == "missing"
    assert client.post("/api/v1/ops/templates/install", headers=_h(w.foh)).status_code == 403
    r = client.post("/api/v1/ops/templates/install", headers=_h(w.owner))
    assert r.status_code == 200 and set(r.json()["created"]) == {"ops_alert_v1", "ops_escalation_v1"}
    assert r.json()["template_status"]["ops_alert_v1"] == "draft"
    assert client.post("/api/v1/ops/templates/install", headers=_h(w.owner)).json()["created"] == []
    r = client.put("/api/v1/ops/settings", json={"sla": {"critical": [3, 30]}, "quiet_hours": {"start": "23:00", "end": "06:00"}},
                   headers=_h(w.mgr))
    assert r.status_code == 200 and r.json()["sla"]["critical"] == [3, 30]
    assert client.put("/api/v1/ops/settings", json={"sla": {"urgent": [1, 2]}}, headers=_h(w.mgr)).status_code == 422


def test_escalation_chain_put_validates_and_appends_owner(client, db, w):
    r = client.put("/api/v1/ops/escalation-chains", headers=_h(w.owner), json={
        "duty": "housekeeping", "steps": [{"type": "on_shift"}, {"type": "role", "role": "manager"}]})
    assert r.status_code == 200
    from app.services import roster_service
    assert roster_service.chain_for(db, w.t.id, "housekeeping", None)[-1] == {"type": "role", "role": "owner"}
    bad = client.put("/api/v1/ops/escalation-chains", headers=_h(w.owner), json={"duty": "housekeeping", "steps": [{"type": "role"}]})
    assert bad.status_code == 422
