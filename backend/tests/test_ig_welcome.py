"""Instagram welcome questions and chat menu (services/ig_welcome.py, Automations v2 phase 5).

Saved on the workspace and pushed to Instagram's chat profile; linked items run an automation (igauto:<rule>:start),
unlinked ones arrive as an ordinary message; saved even when Instagram refuses; only this workspace's automations;
owner/manager only; audited.
"""

import uuid

import pytest

from app.models.audit_event import AuditEvent
from app.models.automation import AutomationRule
from app.models.conversation import ChannelType, Conversation
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.services import ig_automation, ig_sequence, ig_welcome


class FakeIG:
    def __init__(self, refuse=False):
        self.calls, self.refuse = [], refuse

    def set_chat_profile(self, ice, menu):
        if self.refuse:
            raise RuntimeError("Instagram 400: (#100) Unsupported request. code 100")
        self.calls.append(("profile", ice, menu))

    def _ok(self, *call):
        self.calls.append(call)
        return {"message_id": f"mid.{len(self.calls)}"}

    def send_text(self, rid, text): return self._ok("text", rid, text)
    def send_quick_replies(self, rid, text, quick): return self._ok("quick", rid, text, quick)
    def send_link_button(self, rid, text, title, url): return self._ok("button", rid, text, title, url)


def _rule(db, tid, name="PRICE"):
    r = AutomationRule(id=str(uuid.uuid4()), tenant_id=tid, name=name, trigger="ig_dm_received",
                       trigger_config={"keywords": ["price"]}, action="send_instagram_quick_reply",
                       action_config={"message": "Here are our prices."}, is_active=True, run_count=0)
    db.add(r)
    db.commit()
    return r


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="Neelgiri", slug=f"n-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.commit()
    return t


def _cfg(rule_id):
    return {
        "questions": [{"question": "What are your prices?", "rule_id": rule_id}, {"question": "Where are you located?"}],
        "menu": [{"title": "Prices", "kind": "automation", "rule_id": rule_id},
                 {"title": "Our website", "kind": "link", "url": "https://neelgiri.example.in"},
                 {"title": "Talk to us", "kind": "message"}],
    }


def test_save_stores_pushes_and_audits(db, monkeypatch):
    t = _tenant(db)
    r = _rule(db, t.id)
    fake = FakeIG()
    monkeypatch.setattr(ig_automation, "_adapter", lambda db, tenant_id: fake)
    out = ig_welcome.save(db, t, None, _cfg(r.id))
    assert out["pushed"] is True and out["error"] is None
    _, ice, menu = fake.calls[-1]
    assert ice == [{"question": "What are your prices?", "payload": f"igauto:{r.id}:start"},
                   {"question": "Where are you located?", "payload": "igwelcome:q1"}]
    assert menu[0] == {"type": "postback", "title": "Prices", "payload": f"igauto:{r.id}:start"}
    assert menu[1] == {"type": "web_url", "title": "Our website", "url": "https://neelgiri.example.in"}
    assert menu[2]["payload"] == "igwelcome:m2"
    db.refresh(t)
    assert ig_welcome.get(t)["questions"][0]["question"] == "What are your prices?"
    assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="instagram.welcome_updated").count() == 1


def test_refused_by_instagram_is_still_saved_with_the_reason(db, monkeypatch):
    t = _tenant(db)
    monkeypatch.setattr(ig_automation, "_adapter", lambda db, tenant_id: FakeIG(refuse=True))
    out = ig_welcome.save(db, t, None, {"questions": [{"question": "Prices?"}]})
    assert out["pushed"] is False and "Unsupported request" in out["error"]
    db.refresh(t)
    assert ig_welcome.get(t)["questions"] == [{"question": "Prices?", "rule_id": None}]


def test_only_this_workspaces_automations_can_be_linked(db, monkeypatch):
    t = _tenant(db)
    other = _tenant(db)
    foreign = _rule(db, other.id)
    monkeypatch.setattr(ig_automation, "_adapter", lambda db, tenant_id: FakeIG())
    with pytest.raises(ig_welcome.WelcomeError):
        ig_welcome.save(db, t, None, {"questions": [{"question": "Prices?", "rule_id": foreign.id}]})


def test_a_linked_question_runs_its_automation(db, monkeypatch):
    t = _tenant(db)
    r = _rule(db, t.id)
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Ananya")
    c = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel=ChannelType.INSTAGRAM)
    db.add_all([g, c])
    db.commit()
    fake = FakeIG()
    monkeypatch.setattr(ig_automation, "_adapter", lambda db, tenant_id: fake)
    monkeypatch.setattr(ig_sequence, "_queue", lambda *a: None)
    assert ig_automation.handle_payload(db, t.id, f"igauto:{r.id}:start", recipient_id="igsid", guest_id=g.id,
                                        conversation_id=c.id, guest=g)
    assert fake.calls[-1] == ("text", "igsid", "Here are our prices.")
    assert ig_automation.parse_payload("igwelcome:q1") is None          # unlinked: an ordinary message for rules/AI


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def test_endpoints_happy_path_validation_and_roles(client, db, tenant_and_user, monkeypatch):
    from app.core.security import create_access_token
    from app.models.user import User, UserRole

    monkeypatch.setattr(ig_automation, "_adapter", lambda db, tenant_id: FakeIG())
    t = tenant_and_user["tenant"]
    r = _rule(db, t.id)
    res = client.put("/api/v1/instagram/welcome", json=_cfg(r.id), headers=_h(tenant_and_user))
    assert res.status_code == 200 and res.json()["pushed"] is True
    got = client.get("/api/v1/instagram/welcome", headers=_h(tenant_and_user)).json()
    assert len(got["questions"]) == 2 and len(got["menu"]) == 3
    bad = client.put("/api/v1/instagram/welcome", json={"menu": [{"title": "Site", "kind": "link", "url": "http://x"}]},
                     headers=_h(tenant_and_user))
    assert bad.status_code == 422 and "https://" in bad.json()["detail"]
    too_many = client.put("/api/v1/instagram/welcome", json={"questions": [{"question": f"Q{i}"} for i in range(5)]},
                          headers=_h(tenant_and_user))
    assert too_many.status_code == 422
    u = User(id=str(uuid.uuid4()), tenant_id=t.id, name="FOH", email=f"f{uuid.uuid4().hex[:6]}@x.in",
             hashed_password="x", role=UserRole.FOH, is_active=True)
    db.add(u)
    db.commit()
    h = {"Authorization": f"Bearer {create_access_token({'sub': u.id, 'tenant_id': t.id, 'role': u.role.value})}"}
    assert client.get("/api/v1/instagram/welcome", headers=h).status_code == 403
    assert client.put("/api/v1/instagram/welcome", json={}, headers=h).status_code == 403


def test_endpoint_cannot_link_another_workspaces_automation(client, db, tenant_and_user, monkeypatch):
    monkeypatch.setattr(ig_automation, "_adapter", lambda db, tenant_id: FakeIG())
    other = _tenant(db)
    foreign = _rule(db, other.id)
    res = client.put("/api/v1/instagram/welcome", json={"questions": [{"question": "Prices?", "rule_id": foreign.id}]},
                     headers=_h(tenant_and_user))
    assert res.status_code == 422
