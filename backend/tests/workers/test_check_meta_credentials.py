"""
Tests for the proactive WhatsApp/Instagram access-token health check.

Real incident that motivated this: Ratha's Instagram access token
expired (~60-day Meta long-lived token lifetime) with zero monitoring in
place -- every outbound send failed silently for weeks until an agent
noticed a stuck conversation. This task makes one cheap read-only Graph
API call per active integration and alerts owner/manager by email when
Meta rejects it, deduped to once per 24h per (tenant, channel).
"""
import uuid
from unittest.mock import patch, MagicMock

from app.core.encryption import encrypt_credentials
from app.models.integration import Integration
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.workers.tasks.check_meta_credentials import check_tenant_credentials


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _make_whatsapp_integration(db, tenant_id, phone_number_id="pn123", access_token="real-token"):
    integ = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant_id, kind="whatsapp_meta", status="active",
        config={"phone_number_id": phone_number_id},
        credentials_kms_blob=encrypt_credentials({"access_token": access_token}),
    )
    db.add(integ); db.commit()
    return integ


def _make_instagram_integration(db, tenant_id, ig_account_id="ig123", access_token="real-token"):
    integ = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant_id, kind="instagram", status="active",
        config={"instagram_business_account_id": ig_account_id},
        credentials_kms_blob=encrypt_credentials({"access_token": access_token}),
    )
    db.add(integ); db.commit()
    return integ


def _make_manager(db, tenant_id, email="owner@ratha.test"):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id, email=email, name="Owner",
        role=UserRole.OWNER, is_active=True, is_deleted=False,
    )
    db.add(u); db.commit()
    return u


class _FakeResp:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("error", request=MagicMock(), response=self)


class TestCheckTenantCredentials:
    def test_valid_whatsapp_token_sends_no_alert(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        _make_whatsapp_integration(db, tenant_id)

        with patch("app.workers.tasks.check_meta_credentials.SessionLocal", return_value=db), \
             patch("httpx.get", return_value=_FakeResp(200)), \
             patch("app.services.email_service.send_integration_expired_alert_email") as mock_email:
            result = check_tenant_credentials.run(tenant_id=tenant_id)

        assert result["alerts_sent"] == 0
        assert not mock_email.called

    def test_dead_whatsapp_token_alerts_owner(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        _make_whatsapp_integration(db, tenant_id)
        owner_email = tenant_and_user["user"].email

        with patch("app.workers.tasks.check_meta_credentials.SessionLocal", return_value=db), \
             patch("httpx.get", return_value=_FakeResp(403, "Error validating access token")), \
             patch("app.services.email_service.send_integration_expired_alert_email") as mock_email:
            result = check_tenant_credentials.run(tenant_id=tenant_id)

        assert result["alerts_sent"] == 1
        assert mock_email.called
        _, kwargs = mock_email.call_args
        assert kwargs["to_email"] == owner_email
        assert kwargs["channel"] == "whatsapp"

    def test_dead_instagram_token_alerts_owner_independently_of_whatsapp(self, db, tenant_and_user):
        """Confirmed live: WhatsApp and Instagram credentials are entirely
        separate Integration rows -- one channel dying must not be masked
        by (or mistaken for) the other's health."""
        tenant_id = _tenant_id(tenant_and_user)
        _make_whatsapp_integration(db, tenant_id)
        _make_instagram_integration(db, tenant_id)

        def _fake_get(url, **kwargs):
            if "graph.instagram.com" in url:
                return _FakeResp(403, "Invalid OAuth access token")
            return _FakeResp(200)

        with patch("app.workers.tasks.check_meta_credentials.SessionLocal", return_value=db), \
             patch("httpx.get", side_effect=_fake_get), \
             patch("app.services.email_service.send_integration_expired_alert_email") as mock_email:
            result = check_tenant_credentials.run(tenant_id=tenant_id)

        assert result["alerts_sent"] == 1
        _, kwargs = mock_email.call_args
        assert kwargs["channel"] == "instagram"

    def test_repeat_failure_within_24h_does_not_resend(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        _make_whatsapp_integration(db, tenant_id)

        with patch("app.workers.tasks.check_meta_credentials.SessionLocal", return_value=db), \
             patch("httpx.get", return_value=_FakeResp(403, "dead")), \
             patch("app.services.email_service.send_integration_expired_alert_email") as mock_email:
            check_tenant_credentials.run(tenant_id=tenant_id)
            result = check_tenant_credentials.run(tenant_id=tenant_id)

        assert mock_email.call_count == 1
        assert result["alerts_sent"] == 0

    def test_not_configured_channel_is_skipped_silently(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        _make_manager(db, tenant_id)  # no integrations at all

        with patch("app.workers.tasks.check_meta_credentials.SessionLocal", return_value=db), \
             patch("httpx.get") as mock_get, \
             patch("app.services.email_service.send_integration_expired_alert_email") as mock_email:
            result = check_tenant_credentials.run(tenant_id=tenant_id)

        assert result["alerts_sent"] == 0
        assert not mock_get.called
        assert not mock_email.called

    def test_network_error_does_not_alert(self, db, tenant_and_user):
        """A timeout/connection error is not proof the token is dead --
        must not fire a false alarm."""
        tenant_id = _tenant_id(tenant_and_user)
        _make_whatsapp_integration(db, tenant_id)
        _make_manager(db, tenant_id)

        with patch("app.workers.tasks.check_meta_credentials.SessionLocal", return_value=db), \
             patch("httpx.get", side_effect=TimeoutError("connect timeout")), \
             patch("app.services.email_service.send_integration_expired_alert_email") as mock_email:
            result = check_tenant_credentials.run(tenant_id=tenant_id)

        assert result["alerts_sent"] == 0
        assert not mock_email.called
