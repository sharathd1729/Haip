"""POST /calls/click-to-call can name a lead instead of a number.

Real bug (Leads360, "Shared a number -- call them"): the Call button on each
lead only opened the lead page. The list cards don't carry the guest's phone
number (and shouldn't: it stays server-side), so the button had nothing to
dial with. The endpoint now accepts `inquiry_id` and looks the number up
itself, scoped to the caller's workspace.
"""
import os
import uuid

from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.adapters.ivr.vobiz import VobizAdapter
from app.core.config import settings
from app.core.encryption import encrypt_credentials
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.integration import Integration
from app.models.tenant import Tenant


def _vobiz(db, tenant):
    tenant.ivr_provider = "vobiz"
    db.add(Integration(
        id=str(uuid.uuid4()), tenant_id=tenant.id, kind="vobiz", status="active",
        credentials_kms_blob=encrypt_credentials({
            "webhook_secret": "wh-secret", "api_key": "MA123", "api_secret": "tok",
            "forward_number": "+919000000000", "did_number": "+912271264296",
        }),
    ))
    db.commit()


def _lead(db, tenant_id, phone="+919811223344", name="Jai"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, phone=phone)
    db.add(g)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=g.id,
                  stage=InquiryStage.NEW, source=InquirySource.META_IG)
    db.add(inq)
    db.commit()
    return inq


def _stub_provider(monkeypatch):
    calls = []

    async def fake_initiate(self, agent_number, guest_number, *, did_number="", answer_url=""):
        calls.append({"agent": agent_number, "guest": guest_number, "answer_url": answer_url})
        return "req-1"

    monkeypatch.setattr(settings, "API_BASE_URL", "https://haip.example.test")
    monkeypatch.setattr(VobizAdapter, "initiate_click_to_call", fake_initiate)
    return calls


def _post(client, tenant_and_user, body):
    return client.post("/api/v1/calls/click-to-call", json=body,
                       headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"})


def test_calling_a_lead_dials_that_leads_number(client, tenant_and_user, db, monkeypatch):
    _vobiz(db, tenant_and_user["tenant"])
    lead = _lead(db, tenant_and_user["tenant"].id, phone="+919811223344")
    calls = _stub_provider(monkeypatch)

    res = _post(client, tenant_and_user, {"inquiry_id": lead.id})

    assert res.status_code == 200, res.text
    assert res.json() == {"status": "initiated", "provider_call_id": "req-1"}
    assert [c["guest"] for c in calls] == ["+919811223344"]
    assert "guest_number=%2B919811223344" in calls[0]["answer_url"]


def test_a_lead_with_no_number_is_a_clear_error_and_nothing_is_dialled(client, tenant_and_user, db, monkeypatch):
    _vobiz(db, tenant_and_user["tenant"])
    lead = _lead(db, tenant_and_user["tenant"].id, phone="")
    calls = _stub_provider(monkeypatch)

    res = _post(client, tenant_and_user, {"inquiry_id": lead.id})

    assert res.status_code == 400
    assert "hasn't shared a phone number" in res.json()["detail"]
    assert calls == []


def test_another_workspaces_lead_cannot_be_called(client, tenant_and_user, db, monkeypatch):
    _vobiz(db, tenant_and_user["tenant"])
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.flush()
    theirs = _lead(db, other.id, phone="+919899999999")
    calls = _stub_provider(monkeypatch)

    res = _post(client, tenant_and_user, {"inquiry_id": theirs.id})

    assert res.status_code == 404
    assert calls == []


def test_naming_nobody_is_rejected(client, tenant_and_user, db, monkeypatch):
    _vobiz(db, tenant_and_user["tenant"])
    calls = _stub_provider(monkeypatch)

    res = _post(client, tenant_and_user, {})

    assert res.status_code == 422
    assert calls == []


def test_an_explicit_number_still_works_and_wins(client, tenant_and_user, db, monkeypatch):
    _vobiz(db, tenant_and_user["tenant"])
    lead = _lead(db, tenant_and_user["tenant"].id, phone="+919811223344")
    calls = _stub_provider(monkeypatch)

    res = _post(client, tenant_and_user, {"guest_number": "+919000011111", "inquiry_id": lead.id})

    assert res.status_code == 200
    assert [c["guest"] for c in calls] == ["+919000011111"]
