"""GET /security/status: Settings › Security shows only what the running configuration supports."""

import uuid

from app.core.config import settings
from app.core.security import create_access_token
from app.models.user import User, UserRole
from app.services import security_status


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_owner_sees_storage_and_key_names_but_never_values(client, tenant_and_user, monkeypatch):
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "AKIA-test-not-real")
    monkeypatch.setattr(settings, "AWS_SECRET_ACCESS_KEY", "secret-test-not-real")
    monkeypatch.setattr(settings, "AWS_S3_ENDPOINT_URL", "https://abc.r2.cloudflarestorage.com")
    monkeypatch.setattr(settings, "TRANSCRIPTION_PROVIDER", "sarvam")
    monkeypatch.setattr(settings, "DEEPGRAM_API_KEY", "")
    res = client.get("/api/v1/security/status", headers=_h(tenant_and_user["access_token"]))
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["storage"]["provider"] == "cloudflare_r2" and "KMS" not in data["storage"]["text"]
    keys = {k["name"]: k["status"] for k in data["keys"]}
    assert (
        keys["AWS_ACCESS_KEY_ID"] == "set"
        and keys["DEEPGRAM_API_KEY"] == "not_used"
        and keys["KMS_KEY_ID"] == "not_used"
    )
    assert "AKIA-test-not-real" not in res.text and "secret-test-not-real" not in res.text
    assert data["session"]["mfa_enabled_for_you"] is False


def test_storage_claims_follow_the_configuration(monkeypatch):
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "")
    assert security_status.storage()["provider"] == "not_configured"
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "k")
    monkeypatch.setattr(settings, "AWS_SECRET_ACCESS_KEY", "s")
    monkeypatch.setattr(settings, "AWS_S3_ENDPOINT_URL", "")
    monkeypatch.setattr(settings, "KMS_KEY_ID", "arn:aws:kms:test")
    out = security_status.storage()
    assert out["encryption"] == "aws_kms" and "per tenant" not in out["text"]


def test_staff_roles_cannot_read_server_configuration(client, db, tenant_and_user):
    t = tenant_and_user["tenant"]
    u = User(
        id=str(uuid.uuid4()),
        tenant_id=t.id,
        name="Agent",
        email=f"a-{uuid.uuid4().hex[:6]}@t.com",
        role=UserRole.CONCIERGE,
        is_active=True,
    )
    db.add(u)
    db.commit()
    token = create_access_token({"sub": u.id, "tenant_id": t.id, "role": u.role.value})
    assert client.get("/api/v1/security/status", headers=_h(token)).status_code == 403
