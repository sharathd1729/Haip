"""Phase 3 tests (HAIP_MCP_Connector_Plan.md, ticket 3.7): PII masking by
default, reveal_guest_contact's capability gate + dedicated audit action,
the untrusted-content envelope on guest-authored text, and write-tool
idempotency dedup.
"""
import uuid
from unittest.mock import patch

import pytest

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage, InquirySource
from app.models.pipeline_stage import PipelineStage
from app.models.audit_event import AuditEvent
from app.models.capability import Capability
from app.core.security import get_password_hash
from app.services import authz_service, token_service

_ALL_TOOL_CAPS = [
    ("leads.read", "Leads read", "leads", False, "low"),
    ("leads.write", "Leads write", "leads", True, "medium"),
    ("conversations.read", "Conversations read", "conversations", False, "low"),
    ("guests.read", "Guests read", "guests", False, "low"),
    ("guests.pii.reveal", "Reveal guest PII", "guests", False, "high"),
]


def _seed_capabilities(db, *tenant_ids):
    if db.query(Capability.key).first() is None:
        for key, label, category, is_write, risk in _ALL_TOOL_CAPS:
            db.add(Capability(key=key, label=label, category=category, is_write=is_write, risk=risk))
        db.commit()
    for tenant_id in tenant_ids:
        authz_service.seed_default_capabilities(db, tenant_id)


def _make_tenant(db, name="T"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"slug-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush(); return t


def _make_user(db, tenant_id, role=UserRole.OWNER):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id,
        name="Test User", email=f"u-{uuid.uuid4().hex[:6]}@test.com",
        hashed_password=get_password_hash("pw"), role=role, is_active=True,
    )
    db.add(u); db.flush(); return u


class _NoCloseSession:
    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def close(self):
        pass


def _jsonrpc(client, db, raw_pat, method, params=None):
    with patch("app.mcp.server.SessionLocal", lambda: _NoCloseSession(db)):
        return client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
            headers={"Authorization": f"Bearer {raw_pat}"},
        )


class _FakeRedis:
    """In-memory Redis stand-in -- Redis is unreachable in this test
    environment, and idem_check_and_set() fails OPEN (always "first time")
    without a real client, which would make the dedup test vacuous."""
    def __init__(self):
        self.store = {}

    def ping(self):
        return True

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value

    def scan_iter(self, pattern, count=100):
        import fnmatch
        return [k for k in list(self.store.keys()) if fnmatch.fnmatch(k, pattern)]

    def delete(self, *keys):
        for k in keys:
            self.store.pop(k, None)


@pytest.fixture()
def fake_redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr("app.core.cache._client", lambda: fake)
    monkeypatch.setattr("app.core.cache._redis_client", None)
    return fake


class TestMaskedOutputByDefault:
    def test_search_guests_masks_phone_and_email(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant.id)

        db.add(Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, name="Priya Sharma",
                      phone="+919876543210", email="priya@example.com"))
        db.commit()

        raw_pat, _ = token_service.generate_token(db, tenant.id, owner.id, "Claude")
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/call", {
            "name": "search_guests", "arguments": {"query": "Priya"},
        })
        assert resp.status_code == 200
        text = resp.json()["result"]["content"][0]["text"]
        assert "+919876543210" not in text
        assert "priya@example.com" not in text
        # json.dumps ASCII-escapes the bullet mask char to • by default.
        assert "\\u2022" in text


class TestRevealGuestContact:
    def test_denied_without_capability(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        # Seed catalogue but strip guests.pii.reveal from the owner's grant
        # to simulate a tenant that's explicitly denied it.
        _seed_capabilities(db, tenant.id)
        from app.models.capability import RoleCapability
        row = db.query(RoleCapability).filter_by(tenant_id=tenant.id, role="owner", capability_key="guests.pii.reveal").first()
        row.allowed = False
        db.commit()

        guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, name="Priya", phone="+919876543210")
        db.add(guest); db.commit()

        raw_pat, _ = token_service.generate_token(db, tenant.id, owner.id, "Claude")
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/call", {
            "name": "reveal_guest_contact", "arguments": {"guest_id": guest.id},
        })
        assert resp.json()["error"]["code"] == -32001

    def test_granted_reveals_unmasked_and_writes_pii_audit_event(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant.id)

        guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, name="Priya", phone="+919876543210", email="priya@example.com")
        db.add(guest); db.commit()

        raw_pat, _ = token_service.generate_token(db, tenant.id, owner.id, "Claude")
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/call", {
            "name": "reveal_guest_contact", "arguments": {"guest_id": guest.id},
        })
        assert resp.status_code == 200
        result = resp.json()["result"]
        assert result["isError"] is False
        assert "+919876543210" in result["content"][0]["text"]

        events = db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="mcp.pii.reveal").all()
        assert len(events) == 1
        assert events[0].target_type == "guest"
        assert events[0].target_id == guest.id
        # Not double-audited under the generic action name too.
        generic = db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="mcp.tool.reveal_guest_contact").all()
        assert len(generic) == 0


class TestUntrustedContentEnvelope:
    def test_conversation_thread_is_enveloped(self, client, db):
        from app.models.conversation import Conversation

        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant.id)

        guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, name="Guest", phone="+910000000099")
        db.add(guest); db.flush()
        convo = Conversation(id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=guest.id, channel="whatsapp", is_open=True)
        db.add(convo); db.commit()

        raw_pat, _ = token_service.generate_token(db, tenant.id, owner.id, "Claude")
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/call", {
            "name": "get_conversation_thread", "arguments": {"conversation_id": convo.id},
        })
        assert resp.status_code == 200
        text = resp.json()["result"]["content"][0]["text"]
        assert "_warning" in text
        assert "untrusted" in text.lower()


class TestWriteToolIdempotency:
    def test_missing_confirm_is_blocked(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant.id)
        inquiry_id = _create_lead(db, tenant.id)

        raw_pat, _ = token_service.generate_token(db, tenant.id, owner.id, "Claude")
        db.commit()

        resp = _jsonrpc(client, db, raw_pat, "tools/call", {
            "name": "add_note", "arguments": {"inquiry_id": inquiry_id, "note": "hi"},
        })
        assert resp.status_code == 200
        assert resp.json()["result"]["isError"] is True
        assert "confirm" in resp.json()["result"]["content"][0]["text"].lower()

    def test_duplicate_idempotency_key_skips_second_write(self, client, db, fake_redis):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id, role=UserRole.OWNER)
        db.commit()
        _seed_capabilities(db, tenant.id)
        inquiry_id = _create_lead(db, tenant.id)

        raw_pat, _ = token_service.generate_token(db, tenant.id, owner.id, "Claude")
        db.commit()

        args = {
            "inquiry_id": inquiry_id, "note": "Called back, follow up Monday",
            "confirm": True, "idempotency_key": "same-key-123",
        }
        first = _jsonrpc(client, db, raw_pat, "tools/call", {"name": "add_note", "arguments": args})
        assert first.json()["result"]["isError"] is False

        second = _jsonrpc(client, db, raw_pat, "tools/call", {"name": "add_note", "arguments": args})
        assert second.status_code == 200
        second_result = second.json()["result"]
        assert second_result["isError"] is False
        assert "duplicate" in second_result["content"][0]["text"].lower()

        # Only the first call actually created a note -- check via the
        # inquiry's notes conversation message count rather than assuming
        # any particular audit-row count (both calls still each get their
        # own audit row per D4; this checks the underlying write itself).
        from app.models.conversation import Message
        notes = db.query(Message).filter_by(tenant_id=tenant.id).all()
        assert len(notes) == 1


def _create_lead(db, tenant_id: str) -> str:
    stage = PipelineStage(
        id=str(uuid.uuid4()), tenant_id=tenant_id, key="active", label="Active",
        category="valid", order=2, is_valid_lead_entry=True,
    )
    db.add(stage)
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Test Guest", phone="+919999900002")
    db.add(guest)
    db.flush()
    inquiry = Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id,
        stage_id=stage.id, source=InquirySource.PHONE,
    )
    db.add(inquiry)
    db.commit()
    return inquiry.id
