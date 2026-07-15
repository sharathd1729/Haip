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


@pytest.fixture()
def wa_template(db, tenant_and_user):
    tenant_id = tenant_and_user["tenant"]["id"] if isinstance(tenant_and_user["tenant"], dict) else tenant_and_user["tenant"].id
    tmpl = WATemplate(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name="booking_confirmation",
        status=TemplateStatus.DRAFT, components=[{"type": "BODY", "text": "Hi {{1}}"}],
    )
    db.add(tmpl)
    integ = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant_id, kind="whatsapp_meta", status="active",
        config={"access_token": "tok", "waba_id": "waba123"},
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
