"""
WhatsApp module Phase 1, T1.3 — identity resolution routed through
identity_service instead of direct Guest.filter_by(), per CLAUDE.md:
"identity_service is the only place for GID resolution -- never in
endpoints or other services."
"""
import uuid
from unittest.mock import patch
import pytest

from app.models.tenant import Tenant
from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity, IdentityType
from app.workers.tasks import whatsapp as mod


class _NoCloseSessionWrapper:
    def __init__(self, real_db):
        self._real_db = real_db

    def __getattr__(self, name):
        return getattr(self._real_db, name)

    def close(self):
        pass


def _make_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def test_two_messages_same_phone_resolve_to_one_guest(db):
    """Same signal (phone) across two separate inbound messages must
    resolve to the same GID via identity_service, not create duplicate
    guests -- the exact bug class CLAUDE.md's rule guards against."""
    t = _make_tenant(db)

    msg1 = {"from": "919876543210", "id": "wamid.1", "type": "text", "text": {"body": "Hi"}}
    msg2 = {"from": "919876543210", "id": "wamid.2", "type": "text", "text": {"body": "Hello again"}}

    with patch.object(mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)):
        mod._handle_inbound_message(db, t, msg1, contacts=[])
        db.commit()
        mod._handle_inbound_message(db, t, msg2, contacts=[])
        db.commit()

    guests = db.query(Guest).filter_by(tenant_id=t.id, phone="+919876543210").all()
    assert len(guests) == 1

    signals = db.query(GuestIdentity).filter_by(
        tenant_id=t.id, guest_id=guests[0].id, identity_type=IdentityType.PHONE.value,
    ).all()
    assert len(signals) == 1
    assert signals[0].identity_value == "+919876543210"


def test_identity_resolution_goes_through_facade_not_direct_filter():
    """Static guard: no direct Guest.filter_by(phone=...) resolution
    pattern should remain in this module outside of loading an already-
    resolved guest by its canonical id."""
    import inspect
    source = inspect.getsource(mod._handle_inbound_message)
    assert "Guest).filter_by(id=guest_id" in source
    assert "Guest).filter_by(tenant_id=tenant.id, phone=" not in source
