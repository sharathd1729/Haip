"""
WhatsApp module bug-fix pass — waba_id enforcement.

The connect-key UI already requires waba_id client-side (canSubmit in
integrations/page.tsx), but nothing enforced it server-side -- a connect
via direct API (or a pre-existing integration row) could end up with no
waba_id, which submit_template needs and fails on opaquely much later.
"""
from unittest.mock import patch


def test_connect_without_waba_id_is_rejected(client, tenant_and_user):
    headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    with patch("httpx.get", side_effect=Exception("no network in test")):
        resp = client.post(
            "/api/v1/integrations/whatsapp_meta/connect-key",
            json={"phone_number_id": "123", "access_token": "tok"},  # no waba_id
            headers=headers,
        )
    assert resp.status_code == 400
    assert "waba_id" in resp.json()["detail"]


def test_connect_with_waba_id_succeeds(client, tenant_and_user):
    headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    with patch("httpx.get", side_effect=Exception("no network in test")):
        resp = client.post(
            "/api/v1/integrations/whatsapp_meta/connect-key",
            json={"phone_number_id": "123", "access_token": "tok", "waba_id": "waba123"},
            headers=headers,
        )
    assert resp.status_code == 200
    assert resp.json()["waba_id"] == "waba123"
