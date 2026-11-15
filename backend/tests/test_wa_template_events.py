"""Meta template webhooks (services/wa_template_events.py): status changes apply at once; quality/category updates
and unknown templates queue a sync; the workspace is found by its WABA id (events carry no phone number)."""
import hashlib
import hmac
import json
import uuid
from unittest.mock import patch

import pytest

from app.api.v1.endpoints.messaging import TemplateStatus, WATemplate
from app.core.encryption import encrypt_credentials
from app.models.integration import Integration
from app.models.tenant import Tenant
from app.services import wa_template_events as ev


def _world(db, waba="waba-77", secret="s3cret"):
    t = Tenant(id=str(uuid.uuid4()), name="Neelgiri", slug=f"n-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    db.add(Integration(id=str(uuid.uuid4()), tenant_id=t.id, kind="whatsapp_meta", status="active",
                       config={"phone_number_id": f"pn-{waba}", "waba_id": waba},
                       credentials_kms_blob=encrypt_credentials({"access_token": "tok", "app_secret": secret})))
    tmpl = WATemplate(id=str(uuid.uuid4()), tenant_id=t.id, name="stay_reminder", language="en", category="UTILITY",
                      status=TemplateStatus.PENDING, meta_template_id="9001", components=[])
    db.add(tmpl)
    db.commit()
    return t, tmpl


@pytest.fixture
def syncs(monkeypatch):
    out = []
    monkeypatch.setattr(ev, "_queue_sync", lambda tid: out.append(tid))
    return out


def test_approved_and_paused_apply_at_once(db, syncs):
    t, tmpl = _world(db)
    ev.handle(db, "waba-77", "message_template_status_update", {"event": "APPROVED", "message_template_id": 9001})
    db.refresh(tmpl)
    assert tmpl.status == TemplateStatus.APPROVED and tmpl.rejection_reason is None
    ev.handle(db, "waba-77", "message_template_status_update", {"event": "PAUSED", "message_template_id": 9001})
    db.refresh(tmpl)
    assert tmpl.status == TemplateStatus.REJECTED and tmpl.rejection_reason.startswith("Paused by Meta")
    assert syncs == []


def test_rejected_by_name_with_metas_reason(db, syncs):
    t, tmpl = _world(db)
    ev.handle(db, "waba-77", "message_template_status_update",
              {"event": "REJECTED", "message_template_name": "stay_reminder", "message_template_language": "en",
               "reason": "INVALID_FORMAT"})
    db.refresh(tmpl)
    assert tmpl.status == TemplateStatus.REJECTED and tmpl.rejection_reason == "Invalid format"


def test_unknown_templates_and_quality_updates_queue_a_sync(db, syncs):
    t, tmpl = _world(db)
    ev.handle(db, "waba-77", "message_template_status_update", {"event": "APPROVED", "message_template_id": 1})
    ev.handle(db, "waba-77", "message_template_quality_update", {"new_quality_score": "RED"})
    assert syncs == [t.id, t.id]


def test_another_workspaces_waba_never_touches_this_one(db, syncs):
    t, tmpl = _world(db)
    _world(db, waba="waba-other")
    assert ev.handle(db, "waba-nobody", "message_template_status_update", {"event": "APPROVED"}) == "no workspace"
    ev.handle(db, "waba-other", "message_template_status_update", {"event": "APPROVED", "message_template_id": 9001})
    db.refresh(tmpl)
    assert tmpl.status == TemplateStatus.PENDING


class _NoClose:
    def __init__(self, s):
        self._s = s

    def __getattr__(self, name):
        return getattr(self._s, name)

    def close(self):
        pass


def test_the_webhook_accepts_a_signed_waba_event(client, db):
    t, tmpl = _world(db, waba="waba-88", secret="abc123")
    body = json.dumps({"object": "whatsapp_business_account", "entry": [{"id": "waba-88", "changes": [
        {"field": "message_template_status_update", "value": {"event": "APPROVED", "message_template_id": 9001}}]}]}).encode()
    sig = "sha256=" + hmac.new(b"abc123", body, hashlib.sha256).hexdigest()
    with patch("app.api.v1.endpoints.webhooks_whatsapp.SessionLocal", return_value=_NoClose(db)), \
            patch("app.api.v1.endpoints.webhooks_whatsapp.process_whatsapp_message.delay") as queued:
        res = client.post("/api/v1/webhooks/whatsapp", content=body,
                          headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig})
    assert res.status_code == 200, res.text
    assert queued.called
