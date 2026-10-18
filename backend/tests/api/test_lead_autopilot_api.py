"""Lead autopilot endpoints: settings (owner only to change), Undo and Pin (leads.write, lead visibility), and what the
lead page / Leads list show. Happy path + wrong role (403) + another tenant (404) for each."""
import uuid

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.audit_event import AuditEvent
from app.models.inquiry import Inquiry
from app.models.user import User, UserRole
from app.services import lead_autopilot_service as svc
from tests.conftest import seed_capabilities
from tests.services._autopilot_fixtures import NOW, lead, msg, tenant


def _user(db, tenant_id, role):
    u = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name=role.value, email=f"{uuid.uuid4().hex[:8]}@t.com",
             hashed_password=get_password_hash("pw"), role=role, is_active=True)
    db.add(u)
    db.commit()
    return u


def _h(u):
    return {"Authorization": "Bearer " + create_access_token({"sub": u.id, "tenant_id": u.tenant_id, "role": u.role.value})}


@pytest.fixture()
def world(db):
    t, s = tenant(db, mode="autopilot")
    seed_capabilities(db, t.id)
    _, inq, conv = lead(db, t.id, s["active"])
    msg(db, t.id, conv, "We have cancelled the trip, thanks")
    ev = svc.evaluate(db, t.id, inq.id, now=NOW)
    db.commit()
    other_t, other_s = tenant(db, mode="autopilot")
    seed_capabilities(db, other_t.id)
    return {"t": t, "s": s, "inq": inq, "ev": ev, "other": _user(db, other_t.id, UserRole.OWNER),
            "owner": _user(db, t.id, UserRole.OWNER), "manager": _user(db, t.id, UserRole.MANAGER),
            "agent": _user(db, t.id, UserRole.RESERVATIONS), "viewer": _user(db, t.id, UserRole.READ_ONLY)}


class TestSettings:
    def test_owner_reads_and_changes_settings_audited(self, client, db, world):
        r = client.get("/api/v1/lead-autopilot/settings", headers=_h(world["owner"]))
        assert r.status_code == 200 and r.json()["mode"] == "autopilot" and r.json()["applied_30d"] == 1
        r = client.put("/api/v1/lead-autopilot/settings", json={"mode": "suggest", "ai_threshold": 0.9},
                       headers=_h(world["owner"]))
        assert r.status_code == 200 and r.json()["mode"] == "suggest" and r.json()["ai_threshold"] == 0.9
        assert db.query(AuditEvent).filter_by(tenant_id=world["t"].id, action="lead_autopilot.settings_changed").count() == 1

    def test_manager_can_read_but_not_change(self, client, world):
        assert client.get("/api/v1/lead-autopilot/settings", headers=_h(world["manager"])).status_code == 200
        assert client.put("/api/v1/lead-autopilot/settings", json={"mode": "autopilot"},
                          headers=_h(world["manager"])).status_code == 403
        assert client.get("/api/v1/lead-autopilot/settings", headers=_h(world["agent"])).status_code == 403

    def test_invalid_values_are_rejected(self, client, world):
        r = client.put("/api/v1/lead-autopilot/settings", json={"mode": "yolo"}, headers=_h(world["owner"]))
        assert r.status_code == 422
        r = client.put("/api/v1/lead-autopilot/settings", json={"ai_threshold": 0.1}, headers=_h(world["owner"]))
        assert r.status_code == 422

    def test_brand_config_patch_cannot_bypass_the_owner_only_setting(self, client, world):
        r = client.patch("/api/v1/tenants/me", json={"brand_config": {"lead_autopilot": {"mode": "autopilot"}}},
                         headers=_h(world["manager"]))
        assert r.status_code == 422

    def test_settings_are_per_tenant(self, client, world):
        r = client.get("/api/v1/lead-autopilot/settings", headers=_h(world["other"]))
        assert r.json()["applied_30d"] == 0


class TestUndoAndPin:
    def test_agent_undoes_an_automatic_move(self, client, db, world):
        r = client.post(f"/api/v1/leads/{world['inq'].id}/autopilot/undo", json={"event_id": world["ev"].id},
                        headers=_h(world["agent"]))
        assert r.status_code == 200 and r.json()["last_move"]["status"] == "undone"
        db.expire_all()
        assert db.query(Inquiry).get(world["inq"].id).stage_id == world["s"]["active"].id

    def test_second_undo_conflicts(self, client, world):
        url = f"/api/v1/leads/{world['inq'].id}/autopilot/undo"
        assert client.post(url, json={"event_id": world["ev"].id}, headers=_h(world["owner"])).status_code == 200
        assert client.post(url, json={"event_id": world["ev"].id}, headers=_h(world["owner"])).status_code == 409

    def test_read_only_cannot_undo_or_pin(self, client, world):
        base = f"/api/v1/leads/{world['inq'].id}/autopilot"
        assert client.post(base + "/undo", json={"event_id": world["ev"].id}, headers=_h(world["viewer"])).status_code == 403
        assert client.post(base + "/pin", json={"pinned": True}, headers=_h(world["viewer"])).status_code == 403

    def test_another_tenant_gets_404(self, client, world):
        base = f"/api/v1/leads/{world['inq'].id}/autopilot"
        assert client.post(base + "/undo", json={"event_id": world["ev"].id}, headers=_h(world["other"])).status_code == 404
        assert client.post(base + "/pin", json={"pinned": True}, headers=_h(world["other"])).status_code == 404

    def test_an_agent_cannot_touch_a_peers_lead(self, client, db, world):
        peer = _user(db, world["t"].id, UserRole.CONCIERGE)
        world["inq"].assigned_to = peer.id
        db.commit()
        r = client.post(f"/api/v1/leads/{world['inq'].id}/autopilot/pin", json={"pinned": True}, headers=_h(world["agent"]))
        assert r.status_code == 404

    def test_pin_and_unpin_are_audited(self, client, db, world):
        base = f"/api/v1/leads/{world['inq'].id}/autopilot/pin"
        assert client.post(base, json={"pinned": True}, headers=_h(world["agent"])).json()["pinned"] is True
        assert client.post(base, json={"pinned": False}, headers=_h(world["agent"])).json()["pinned"] is False
        actions = {a for (a,) in db.query(AuditEvent.action).filter(AuditEvent.tenant_id == world["t"].id)}
        assert {"lead_autopilot.pinned", "lead_autopilot.unpinned"} <= actions


class TestLeadViews:
    def test_lead_page_shows_the_move_with_undo(self, client, world):
        r = client.get(f"/api/v1/leads/{world['inq'].id}", headers=_h(world["owner"]))
        assert r.status_code == 200
        block = r.json()["autopilot"]
        assert block["mode"] == "autopilot" and block["last_move"]["can_undo"] is True
        assert block["last_move"]["to_stage_label"] == "Lost" and block["last_move"]["evidence"][0]["kind"] == "message"

    def test_list_badge_and_filter(self, client, db, world):
        lead(db, world["t"].id, world["s"]["active"])                    # a lead nobody automated
        r = client.get("/api/v1/leads?autopilot=moved", headers=_h(world["owner"]))
        assert r.status_code == 200 and r.json()["total"] == 1
        assert r.json()["leads"][0]["autopilot_move"]["to_stage_label"] == "Lost"
        assert client.get("/api/v1/leads", headers=_h(world["owner"])).json()["total"] == 2
        assert client.get("/api/v1/leads?autopilot=bogus", headers=_h(world["owner"])).status_code == 422

    def test_filter_never_shows_another_tenants_moves(self, client, world):
        assert client.get("/api/v1/leads?autopilot=moved", headers=_h(world["other"])).json()["total"] == 0
