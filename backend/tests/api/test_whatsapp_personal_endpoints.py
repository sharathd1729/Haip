"""Personal WhatsApp bridge endpoints: pairing lifecycle (JWT-authed) and
the bridge-facing ingest webhook (per-session secret, no JWT)."""
import os
import uuid
from unittest.mock import patch

from tests.conftest import *  # noqa: F401,F403

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.whatsapp_personal_session import WhatsAppPersonalSession, WhatsAppPersonalSessionStatus


def _headers(fixture):
    return {"Authorization": f"Bearer {fixture['access_token']}"}


def _tenant_id(fixture):
    t = fixture["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _make_user(db, tenant_id, role):
    from app.core.security import create_access_token, get_password_hash
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name=f"{role.value}-user",
        email=f"{role.value}-{uuid.uuid4().hex[:6]}@t.com",
        hashed_password=get_password_hash("testpassword123"), role=role, is_active=True,
    )
    db.add(u); db.commit()
    token = create_access_token(data={"sub": u.id, "tenant_id": tenant_id, "role": role.value})
    return u, {"Authorization": f"Bearer {token}"}


def _ensure_fernet_key():
    from cryptography.fernet import Fernet
    os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()


class TestPairingLifecycle:
    def test_start_pairing_returns_qr(self, client, db, tenant_and_user):
        _ensure_fernet_key()
        with patch("app.services.whatsapp_personal_service.httpx.post") as mock_post:
            mock_post.return_value.raise_for_status = lambda: None
            mock_post.return_value.json = lambda: {"qr_code_data_url": "data:image/png;base64,abc"}
            resp = client.post("/api/v1/whatsapp-personal/sessions", headers=_headers(tenant_and_user))

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["qr_code_data_url"] == "data:image/png;base64,abc"
        assert body["status"] == "pending_pairing"

    def test_bridge_unreachable_returns_502(self, client, db, tenant_and_user):
        with patch("app.services.whatsapp_personal_service.httpx.post", side_effect=Exception("connection refused")):
            resp = client.post("/api/v1/whatsapp-personal/sessions", headers=_headers(tenant_and_user))
        assert resp.status_code == 502

    def test_get_my_session_none_before_pairing(self, client, tenant_and_user):
        resp = client.get("/api/v1/whatsapp-personal/sessions/me", headers=_headers(tenant_and_user))
        assert resp.status_code == 200
        assert resp.json() is None

    def test_logout_with_no_session_is_404(self, client, tenant_and_user):
        resp = client.delete("/api/v1/whatsapp-personal/sessions/me", headers=_headers(tenant_and_user))
        assert resp.status_code == 404

    def test_requires_auth(self, client):
        assert client.post("/api/v1/whatsapp-personal/sessions").status_code in (401, 403)


class TestDirectoryListRoleGate:
    def test_owner_can_list_all_sessions(self, client, db, tenant_and_user):
        resp = client.get("/api/v1/whatsapp-personal/sessions", headers=_headers(tenant_and_user))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_non_owner_manager_is_forbidden(self, client, db, tenant_and_user):
        _, h = _make_user(db, _tenant_id(tenant_and_user), UserRole.RESERVATIONS)
        resp = client.get("/api/v1/whatsapp-personal/sessions", headers=h)
        assert resp.status_code == 403

    def test_directory_masks_phone_but_self_view_shows_it_in_full(self, client, db, tenant_and_user):
        from app.models.whatsapp_personal_session import WhatsAppPersonalSession, WhatsAppPersonalSessionStatus
        agent, agent_headers = _make_user(db, _tenant_id(tenant_and_user), UserRole.RESERVATIONS)
        db.add(WhatsAppPersonalSession(
            id=str(uuid.uuid4()), tenant_id=_tenant_id(tenant_and_user), user_id=agent.id,
            status=WhatsAppPersonalSessionStatus.CONNECTED, phone_number="+919812345678",
        ))
        db.commit()

        directory = client.get("/api/v1/whatsapp-personal/sessions", headers=_headers(tenant_and_user)).json()
        assert directory[0]["phone_number"] != "+919812345678"
        assert directory[0]["phone_number"].endswith("78")
        assert "•" in directory[0]["phone_number"]

        own = client.get("/api/v1/whatsapp-personal/sessions/me", headers=agent_headers).json()
        assert own["phone_number"] == "+919812345678"


class TestBridgeIngestWebhook:
    def _make_session_with_secret(self, db, tenant_id, user_id, secret="valid-secret"):
        _ensure_fernet_key()
        from app.core.encryption import encrypt_credentials
        s = WhatsAppPersonalSession(
            id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id,
            status=WhatsAppPersonalSessionStatus.CONNECTED,
            webhook_secret_enc=encrypt_credentials({"webhook_secret": secret}),
        )
        db.add(s); db.commit()
        return s

    def test_valid_secret_ingests_message(self, client, db, tenant_and_user):
        agent, _ = _make_user(db, _tenant_id(tenant_and_user), UserRole.RESERVATIONS)
        session = self._make_session_with_secret(db, _tenant_id(tenant_and_user), agent.id)

        resp = client.post(
            f"/api/v1/webhooks/whatsapp-personal/{session.id}/message",
            json={"bridge_message_id": "wm-1", "from_phone": "+919812345678", "from_name": "Priya", "body": "hi"},
            headers={"X-Bridge-Secret": "valid-secret"},
        )
        assert resp.status_code == 200, resp.text

    def test_wrong_secret_is_401(self, client, db, tenant_and_user):
        agent, _ = _make_user(db, _tenant_id(tenant_and_user), UserRole.RESERVATIONS)
        session = self._make_session_with_secret(db, _tenant_id(tenant_and_user), agent.id, secret="right-one")

        resp = client.post(
            f"/api/v1/webhooks/whatsapp-personal/{session.id}/message",
            json={"bridge_message_id": "wm-1", "from_phone": "+919812345678", "from_name": "Priya", "body": "hi"},
            headers={"X-Bridge-Secret": "wrong-one"},
        )
        assert resp.status_code == 401

    def test_unknown_session_id_is_404(self, client):
        resp = client.post(
            "/api/v1/webhooks/whatsapp-personal/does-not-exist/message",
            json={"bridge_message_id": "wm-1", "from_phone": "+919812345678", "body": "hi"},
            headers={"X-Bridge-Secret": "anything"},
        )
        assert resp.status_code == 404

    def test_status_update_endpoint_valid_secret(self, client, db, tenant_and_user):
        agent, _ = _make_user(db, _tenant_id(tenant_and_user), UserRole.RESERVATIONS)
        session = self._make_session_with_secret(db, _tenant_id(tenant_and_user), agent.id)

        resp = client.post(
            f"/api/v1/webhooks/whatsapp-personal/{session.id}/status",
            json={"status": "connected", "phone_number": "+919900000000", "device_jid": "abc:1@s.whatsapp.net"},
            headers={"X-Bridge-Secret": "valid-secret"},
        )
        assert resp.status_code == 200, resp.text

        db.refresh(session)
        assert session.status == WhatsAppPersonalSessionStatus.CONNECTED
        assert session.phone_number == "+919900000000"
