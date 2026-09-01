"""Personal/Business-app WhatsApp bridge -- Phase 1 read-only capture.

Covers: inbound ingestion mirrors the official WhatsApp path (guest
resolution, conversation/inquiry creation, ai_mode forced to "shadow"),
duplicate bridge_message_id is a no-op, tenant isolation, and the
per-session webhook-secret verification used by the bridge-facing
endpoint's auth.
"""
import os
import uuid
from unittest.mock import patch

import pytest

from tests.conftest import *  # noqa: F401,F403

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.conversation import Conversation, Message
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.whatsapp_personal_session import WhatsAppPersonalSession, WhatsAppPersonalSessionStatus
from app.services import whatsapp_personal_service as svc


def _ensure_fernet_key():
    from cryptography.fernet import Fernet
    os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()


def _make_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.commit()
    return t


def _make_agent(db, tenant_id, name="Agent Raja"):
    from app.core.security import get_password_hash
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name=name,
        email=f"{name.lower().replace(' ', '.')}-{uuid.uuid4().hex[:6]}@t.com",
        hashed_password=get_password_hash("x123456789"), role=UserRole.RESERVATIONS, is_active=True,
    )
    db.add(u); db.commit()
    return u


def _make_session(db, tenant_id, user_id, secret="test-bridge-secret"):
    _ensure_fernet_key()
    from app.core.encryption import encrypt_credentials
    s = WhatsAppPersonalSession(
        id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id,
        status=WhatsAppPersonalSessionStatus.CONNECTED,
        phone_number="+919900000000",
        webhook_secret_enc=encrypt_credentials({"webhook_secret": secret}),
    )
    db.add(s); db.commit()
    return s


class TestIngestInboundMessage:
    def test_happy_path_creates_guest_conversation_message_and_inquiry(self, db):
        tenant = _make_tenant(db)
        agent = _make_agent(db, tenant.id)
        session = _make_session(db, tenant.id, agent.id)

        msg = svc.ingest_inbound_message(
            db, session,
            bridge_message_id="wm-1", from_phone="+919812345678", from_name="Priya",
            body="Hi, is the caravan free next weekend?",
        )

        assert msg is not None
        assert msg.body == "Hi, is the caravan free next weekend?"
        assert msg.channel_metadata["source"] == "personal_bridge"

        conv = db.query(Conversation).filter_by(id=msg.conversation_id).first()
        assert conv.ai_mode == "shadow"   # never autonomous on this pipe
        assert conv.assigned_to == agent.id

        guest = db.query(Guest).filter_by(id=conv.guest_id, tenant_id=tenant.id).first()
        assert guest is not None
        assert guest.name == "Priya"

        inquiry = db.query(Inquiry).filter_by(id=conv.inquiry_id).first()
        assert inquiry is not None
        assert inquiry.assigned_to == agent.id

    def test_duplicate_bridge_message_id_is_a_noop(self, db):
        tenant = _make_tenant(db)
        agent = _make_agent(db, tenant.id)
        session = _make_session(db, tenant.id, agent.id)

        first = svc.ingest_inbound_message(
            db, session, bridge_message_id="wm-dup", from_phone="+919812345678",
            from_name="Priya", body="first",
        )
        second = svc.ingest_inbound_message(
            db, session, bridge_message_id="wm-dup", from_phone="+919812345678",
            from_name="Priya", body="first",
        )

        assert first is not None
        assert second is None
        assert db.query(Message).filter_by(channel_message_id="wm-dup").count() == 1

    def test_second_message_reuses_open_conversation_no_second_inquiry(self, db):
        tenant = _make_tenant(db)
        agent = _make_agent(db, tenant.id)
        session = _make_session(db, tenant.id, agent.id)

        svc.ingest_inbound_message(
            db, session, bridge_message_id="wm-a", from_phone="+919812345678",
            from_name="Priya", body="Hi",
        )
        svc.ingest_inbound_message(
            db, session, bridge_message_id="wm-b", from_phone="+919812345678",
            from_name="Priya", body="Following up",
        )

        guest = db.query(Guest).filter_by(tenant_id=tenant.id, phone="+919812345678").first()
        conversations = db.query(Conversation).filter_by(tenant_id=tenant.id, guest_id=guest.id).all()
        assert len(conversations) == 1
        assert db.query(Message).filter_by(conversation_id=conversations[0].id).count() == 2
        assert db.query(Inquiry).filter_by(tenant_id=tenant.id, guest_id=guest.id).count() == 1

    def test_tenant_isolation(self, db):
        tenant_a = _make_tenant(db)
        tenant_b = _make_tenant(db)
        agent_a = _make_agent(db, tenant_a.id)
        session_a = _make_session(db, tenant_a.id, agent_a.id)

        svc.ingest_inbound_message(
            db, session_a, bridge_message_id="wm-iso", from_phone="+919812345678",
            from_name="Priya", body="hi",
        )

        # Same phone number, different tenant -- must not resolve to the
        # same guest or be visible in tenant B's data at all.
        guest_b = db.query(Guest).filter_by(tenant_id=tenant_b.id, phone="+919812345678").first()
        assert guest_b is None
        assert db.query(Message).filter_by(tenant_id=tenant_b.id).count() == 0


class TestVerifyBridgeSecret:
    def test_correct_secret_verifies(self, db):
        tenant = _make_tenant(db)
        agent = _make_agent(db, tenant.id)
        session = _make_session(db, tenant.id, agent.id, secret="right-secret")

        assert svc.verify_bridge_secret(session, "right-secret") is True

    def test_wrong_secret_fails(self, db):
        tenant = _make_tenant(db)
        agent = _make_agent(db, tenant.id)
        session = _make_session(db, tenant.id, agent.id, secret="right-secret")

        assert svc.verify_bridge_secret(session, "wrong-secret") is False

    def test_missing_secret_never_verifies(self, db):
        tenant = _make_tenant(db)
        agent = _make_agent(db, tenant.id)
        session = WhatsAppPersonalSession(
            id=str(uuid.uuid4()), tenant_id=tenant.id, user_id=agent.id,
            status=WhatsAppPersonalSessionStatus.PENDING_PAIRING,
        )
        db.add(session); db.commit()

        assert svc.verify_bridge_secret(session, "") is False
        assert svc.verify_bridge_secret(session, "anything") is False


class TestQrRotationCaching:
    """A real pairing attempt failed ("Couldn't link device, try again
    later") because the bridge only ever forwarded the FIRST QR code and
    WhatsApp rotates it roughly every 20-30s -- anyone who took longer
    than one rotation to actually scan was linking an already-expired
    code. The bridge now pushes every rotation here via the status
    webhook; this covers the caching half of that fix (session.go's own
    rotation-forwarding isn't unit-testable from Python)."""

    def _fake_cache(self, monkeypatch):
        store: dict = {}
        monkeypatch.setattr(svc, "get_cached", lambda key: store.get(key))
        monkeypatch.setattr(svc, "set_cached", lambda key, value, ttl=300: store.__setitem__(key, value))
        return store

    def test_rotated_qr_is_cached_and_retrievable(self, db, monkeypatch):
        self._fake_cache(monkeypatch)
        tenant = _make_tenant(db)
        agent = _make_agent(db, tenant.id)
        session = _make_session(db, tenant.id, agent.id)
        session.status = WhatsAppPersonalSessionStatus.PENDING_PAIRING
        db.commit()

        svc.apply_status_update(db, session, status="pending_pairing", qr_code_data_url="data:image/png;base64,ROTATED")

        assert svc.get_cached_qr(session.id) == "data:image/png;base64,ROTATED"

    def test_status_update_without_qr_does_not_clear_a_cached_one(self, db, monkeypatch):
        """An unrelated status ping (e.g. a plain reconnect) must not wipe
        out a QR that's still valid -- only a real rotation event carries
        qr_code_data_url at all."""
        self._fake_cache(monkeypatch)
        tenant = _make_tenant(db)
        agent = _make_agent(db, tenant.id)
        session = _make_session(db, tenant.id, agent.id)

        svc.apply_status_update(db, session, status="pending_pairing", qr_code_data_url="data:image/png;base64,FIRST")
        svc.apply_status_update(db, session, status="pending_pairing")  # no qr this time

        assert svc.get_cached_qr(session.id) == "data:image/png;base64,FIRST"


class TestStartOrRestartPairing:
    def test_calls_bridge_and_persists_encrypted_secret(self, db):
        _ensure_fernet_key()
        tenant = _make_tenant(db)
        agent = _make_agent(db, tenant.id)

        with patch("app.services.whatsapp_personal_service.httpx.post") as mock_post:
            mock_post.return_value.raise_for_status = lambda: None
            mock_post.return_value.json = lambda: {"qr_code_data_url": "data:image/png;base64,xyz"}

            session, qr = svc.start_or_restart_pairing(db, tenant.id, agent.id)

        assert qr == "data:image/png;base64,xyz"
        assert session.status == WhatsAppPersonalSessionStatus.PENDING_PAIRING
        assert session.webhook_secret_enc is not None

        # Re-pairing reuses the same row, not a second one (unique constraint).
        with patch("app.services.whatsapp_personal_service.httpx.post") as mock_post:
            mock_post.return_value.raise_for_status = lambda: None
            mock_post.return_value.json = lambda: {"qr_code_data_url": "data:image/png;base64,new"}
            session2, _ = svc.start_or_restart_pairing(db, tenant.id, agent.id)

        assert session2.id == session.id
        assert db.query(WhatsAppPersonalSession).filter_by(tenant_id=tenant.id, user_id=agent.id).count() == 1
