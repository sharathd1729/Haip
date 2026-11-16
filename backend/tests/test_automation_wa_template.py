"""The 'send WhatsApp template' automation fills the template's variables (automation_engine._action_send_wa_template).

It used to send the template name only, so Meta rejected every template with a {{n}} or a media header.
"""

import uuid

import pytest

from app.api.v1.endpoints.messaging import WATemplate
from app.core.encryption import encrypt_credentials
from app.models.guest import Guest
from app.models.integration import Integration
from app.models.tenant import Tenant
from app.workers.tasks import automation_engine


class FakeWA:
    def __init__(self):
        self.sent = []

    async def send_template(self, to, template_name, language_code="en_US", components=None):
        self.sent.append({"to": to, "name": template_name, "components": components})
        return {"messages": [{"id": "wamid.1"}]}


@pytest.fixture
def world(db, monkeypatch):
    t = Tenant(id=str(uuid.uuid4()), name="Neelgiri", slug=f"n-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Ananya Rao", phone="+919886140372")
    db.add(Integration(tenant_id=t.id, kind="whatsapp_meta", status="active", config={"phone_number_id": "pn1"},
                       credentials_kms_blob=encrypt_credentials({"access_token": "tok"})))
    tmpl = WATemplate(id=str(uuid.uuid4()), tenant_id=t.id, name="stay_reminder", language="en", category="UTILITY",
                      status="approved", meta_template_id="m1",
                      components=[{"type": "BODY", "text": "Hi {{1}}, your stay starts {{2}}."}])
    db.add_all([g, tmpl])
    db.commit()
    fake = FakeWA()
    monkeypatch.setattr("app.adapters.whatsapp.meta_cloud.get_wa_adapter", lambda pn, tok: fake)
    monkeypatch.setattr("app.workers.tasks.whatsapp._get_wa_access_token", lambda db, tid: "tok")
    return t, g, tmpl, fake


def test_variables_are_filled_for_the_guest(db, world):
    t, g, tmpl, fake = world
    vmap = {"body": {"1": {"source": "first_name", "fallback": "there"}, "2": {"source": "static", "value": "tomorrow"}}}
    out = automation_engine._action_send_wa_template(db, {"template_id": tmpl.id, "variable_map": vmap},
                                                     {"guest_id": g.id}, t.id)
    assert out.startswith("Template")
    params = fake.sent[0]["components"][0]["parameters"]
    assert [p["text"] for p in params] == ["Ananya", "tomorrow"]


def test_a_variable_with_no_value_is_skipped_with_the_reason(db, world):
    t, g, tmpl, fake = world
    out = automation_engine._action_send_wa_template(db, {"template_id": tmpl.id}, {"guest_id": g.id}, t.id)
    assert out.startswith("skipped") and "body {{1}}" in out and fake.sent == []


def test_a_media_header_without_a_file_is_caught_before_sending(db, world):
    t, g, tmpl, fake = world
    tmpl.components = [{"type": "HEADER", "format": "IMAGE"}, {"type": "BODY", "text": "Welcome!"}]
    db.commit()
    out = automation_engine._action_send_wa_template(db, {"template_id": tmpl.id}, {"guest_id": g.id}, t.id)
    assert out.startswith("skipped") and "header" in out and fake.sent == []


def test_a_template_without_variables_still_sends(db, world):
    t, g, tmpl, fake = world
    tmpl.components = [{"type": "BODY", "text": "Thanks for staying with us!"}]
    db.commit()
    automation_engine._action_send_wa_template(db, {"template_id": tmpl.id}, {"guest_id": g.id}, t.id)
    assert fake.sent[0]["components"] is None
