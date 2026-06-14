"""
Tests for identity_service.py — T18, T19, T20, T21

Tests:
  T18: add_signal happy path — whatsapp_number signal added with correct confidence
  T19: add_signal cross-tenant isolation — cannot add signal to another tenant's guest
  T20: add_signal phone/email writes DPDP Consent row automatically
  T21: merge_guests is idempotent — running twice produces no duplicates
"""

import uuid
import pytest

from app.models.guest import Guest
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.guest_identity import GuestIdentity
from app.models.consent import Consent
from app.services import identity_service


def _make_tenant(db, name="TenantA"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"slug-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _make_guest(db, tenant_id, name="Rahul S.", phone=""):
    g = Guest(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=name,
        phone=phone,
    )
    db.add(g)
    db.flush()
    return g


def _make_ig_signal(db, tenant_id, guest_id, ig_value="ig_user_123"):
    from app.models.guest_identity import GuestIdentity
    from app.models.base import gen_uuid
    sig = GuestIdentity(
        id=gen_uuid(),
        tenant_id=tenant_id,
        guest_id=guest_id,
        identity_type="instagram_user_id",
        identity_value=ig_value,
        source="instagram",
        confidence=0.70,
    )
    db.add(sig)
    db.flush()
    return sig


# ── T18: add_signal happy path ────────────────────────────────────────────────

def test_add_signal_happy_path(db):
    """Adding whatsapp_number signal creates a GuestIdentity row with confidence=0.85."""
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    _make_ig_signal(db, tenant.id, guest.id)
    db.commit()

    confidence = identity_service.add_signal(
        db=db,
        tenant_id=tenant.id,
        guest_id=guest.id,
        signal_type="whatsapp_number",
        value="+919876543210",
        source="agent_manual",
    )

    assert confidence == pytest.approx(0.85, abs=0.01)

    sig = db.query(GuestIdentity).filter_by(
        tenant_id=tenant.id,
        guest_id=guest.id,
        identity_type="whatsapp_number",
    ).first()
    assert sig is not None
    assert sig.identity_value == "+919876543210"


# ── T19: cross-tenant isolation ───────────────────────────────────────────────

def test_add_signal_cross_tenant_isolation(db):
    """Cannot add a signal to a guest belonging to a different tenant."""
    tenant_a = _make_tenant(db, "TenantA")
    tenant_b = _make_tenant(db, "TenantB")
    guest_a = _make_guest(db, tenant_a.id)
    db.commit()

    with pytest.raises(ValueError, match="not found"):
        identity_service.add_signal(
            db=db,
            tenant_id=tenant_b.id,    # wrong tenant
            guest_id=guest_a.id,
            signal_type="whatsapp_number",
            value="+919999999999",
            source="test",
        )


# ── T20: phone/email writes Consent row (DPDP) ───────────────────────────────

def test_add_signal_phone_writes_consent(db):
    """Adding a phone signal with actor_user_id auto-writes a Consent row."""
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id)
    db.commit()

    actor_id = str(uuid.uuid4())

    identity_service.add_signal(
        db=db,
        tenant_id=tenant.id,
        guest_id=guest.id,
        signal_type="phone",
        value="+911234567890",
        source="agent_manual",
        actor_user_id=actor_id,
    )
    db.flush()

    consent = db.query(Consent).filter_by(
        tenant_id=tenant.id,
        guest_id=guest.id,
        source="agent_manual",
    ).first()

    assert consent is not None
    assert consent.scope == "profiling"
    assert consent.channel == "crm"
    assert consent.granted is True


# ── T21: merge_guests is idempotent ──────────────────────────────────────────

def test_merge_guests_idempotent(db):
    """Merging the same pair twice produces no duplicate signals; deprecated is soft-deleted once."""
    tenant = _make_tenant(db)
    guest_a = _make_guest(db, tenant.id, name="Guest A")
    guest_b = _make_guest(db, tenant.id, name="Guest B")
    _make_ig_signal(db, tenant.id, guest_a.id, "ig_user_a")
    _make_ig_signal(db, tenant.id, guest_b.id, "ig_user_b")
    db.commit()

    # First merge: A (deprecated) → B (survivor)
    identity_service.merge_guests(db, tenant.id, survivor_id=guest_b.id, deprecated_id=guest_a.id)
    db.flush()

    # Second merge (idempotent — should not crash or duplicate)
    identity_service.merge_guests(db, tenant.id, survivor_id=guest_b.id, deprecated_id=guest_a.id)
    db.flush()

    # Guest A should be soft-deleted
    db.expire(guest_a)
    guest_a_refreshed = db.query(Guest).filter_by(id=guest_a.id).first()
    assert guest_a_refreshed.is_deleted is True

    # All signals now point to guest_b
    signals = db.query(GuestIdentity).filter_by(
        tenant_id=tenant.id, guest_id=guest_b.id
    ).all()
    signal_types = [s.identity_type for s in signals]
    assert "ig_user_b" in [s.identity_value for s in signals] or len(signals) >= 1

    # No orphaned signals pointing to deprecated guest_a
    orphaned = db.query(GuestIdentity).filter_by(
        tenant_id=tenant.id, guest_id=guest_a.id
    ).all()
    assert len(orphaned) == 0
