"""
Test for T0.3: submit_template must distinguish a genuine Meta API
failure (SUBMISSION_FAILED) from "awaiting review" (PENDING) -- before
the fix both landed on PENDING, indistinguishable in the UI.
"""
import uuid
from unittest.mock import patch
import pytest

from app.api.v1.endpoints.messaging import WATemplate, TemplateStatus
from app.models.integration import Integration
from app.core.encryption import encrypt_credentials

# access_token is a secret and only ever lives in the encrypted
# credentials_kms_blob (see _get_wa_access_token's docstring in
# app/workers/tasks/whatsapp.py) -- config carries only non-secret fields
# like waba_id, since it's spread wholesale into GET /integrations
# responses. A template needs {{n}} variables to also carry a matching
# example or Meta rejects it regardless of credentials, so every fixture
# below includes one.
_EXAMPLE_COMPONENTS = [{"type": "BODY", "text": "Hi {{1}}", "example": {"body_text": [["Priya"]]}}]


@pytest.fixture()
def wa_template(db, tenant_and_user):
    tenant_id = tenant_and_user["tenant"]["id"] if isinstance(tenant_and_user["tenant"], dict) else tenant_and_user["tenant"].id
    tmpl = WATemplate(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name="booking_confirmation",
        status=TemplateStatus.DRAFT, components=_EXAMPLE_COMPONENTS,
    )
    db.add(tmpl)
    integ = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant_id, kind="whatsapp_meta", status="active",
        config={"waba_id": "waba123"},
        credentials_kms_blob=encrypt_credentials({"access_token": "tok"}),
    )
    db.add(integ)
    db.commit()
    return tmpl


def test_submit_template_marks_submission_failed_on_meta_error(client, db, tenant_and_user, wa_template):
    headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}

    with patch("httpx.post", side_effect=RuntimeError("connection reset")):
        resp = client.post(f"/api/v1/messaging/templates/{wa_template.id}/submit", headers=headers)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "submission_failed"
    assert body["rejection_reason"]

    db.refresh(wa_template)
    assert wa_template.status == TemplateStatus.SUBMISSION_FAILED
    assert wa_template.status != TemplateStatus.PENDING


def test_submit_template_no_integration_fails_loudly(client, db, tenant_and_user):
    """Previously: no Integration row at all silently marked the template
    'Pending' with a 200 response, without ever calling Meta -- the exact
    bug that left a real tenant's template invisible in Meta Business
    Manager forever. Must now surface a real error instead."""
    tenant_id = tenant_and_user["tenant"]["id"] if isinstance(tenant_and_user["tenant"], dict) else tenant_and_user["tenant"].id
    tmpl = WATemplate(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name="no_integration_case",
        status=TemplateStatus.DRAFT, components=_EXAMPLE_COMPONENTS,
    )
    db.add(tmpl)
    db.commit()

    headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    resp = client.post(f"/api/v1/messaging/templates/{tmpl.id}/submit", headers=headers)

    assert resp.status_code == 400
    assert "not connected" in resp.json()["detail"].lower()

    db.refresh(tmpl)
    assert tmpl.status == TemplateStatus.DRAFT  # never silently flipped to PENDING


def test_submit_template_falls_back_to_whatsapp_kind_integration(client, db, tenant_and_user):
    """The bug: this endpoint only looked up kind='whatsapp_meta', while
    every other WhatsApp code path also falls back to kind='whatsapp'. A
    tenant whose integration row uses the 'whatsapp' kind had submission
    silently skipped even though sending/campaigns/sync all worked fine."""
    tenant_id = tenant_and_user["tenant"]["id"] if isinstance(tenant_and_user["tenant"], dict) else tenant_and_user["tenant"].id
    tmpl = WATemplate(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name="whatsapp_kind_case",
        status=TemplateStatus.DRAFT, components=_EXAMPLE_COMPONENTS,
    )
    db.add(tmpl)
    db.add(Integration(
        id=str(uuid.uuid4()), tenant_id=tenant_id, kind="whatsapp", status="active",
        config={"waba_id": "waba123"},
        credentials_kms_blob=encrypt_credentials({"access_token": "tok"}),
    ))
    db.commit()

    headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}

    class _FakeResp:
        def json(self):
            return {"id": "meta-tmpl-id-123"}

    with patch("httpx.post", return_value=_FakeResp()) as mock_post:
        resp = client.post(f"/api/v1/messaging/templates/{tmpl.id}/submit", headers=headers)

    assert mock_post.called  # actually reached Meta this time
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["meta_template_id"] == "meta-tmpl-id-123"
