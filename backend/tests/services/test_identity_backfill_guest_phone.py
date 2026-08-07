"""Regression: identity_resolution.py only ever backfilled the
guests.phone convenience column at guest CREATION time. A phone/
whatsapp_number signal attached to an ALREADY-EXISTING guest later (e.g.
an Instagram-first guest who later calls) never touched guests.phone,
even though it was fully resolvable via guest_identities -- confirmed
live: list_conversations reads guests.phone directly for the inbox card,
so those guests showed no name AND no phone number at all."""
import uuid
import pytest

from app.models.guest import Guest
from app.models.tenant import Tenant
from app.services import identity_service


def _make_tenant(db, name="TenantA"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"slug-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _make_guest(db, tenant_id, name="IG Guest", phone=""):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, phone=phone)
    db.add(g)
    db.flush()
    return g


def test_phone_signal_backfills_empty_guest_phone(db):
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id, phone="")

    identity_service.add_signal(
        db, tenant_id=tenant.id, guest_id=guest.id,
        signal_type="phone", value="+919876543210", source="ivr_call",
    )
    db.commit()

    db.refresh(guest)
    assert guest.phone == "+919876543210"


def test_whatsapp_number_signal_also_backfills_empty_guest_phone(db):
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id, phone="")

    identity_service.add_signal(
        db, tenant_id=tenant.id, guest_id=guest.id,
        signal_type="whatsapp_number", value="+919876543210", source="whatsapp",
    )
    db.commit()

    db.refresh(guest)
    assert guest.phone == "+919876543210"


def test_phone_signal_does_not_overwrite_existing_guest_phone(db):
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id, phone="+911111111111")

    identity_service.add_signal(
        db, tenant_id=tenant.id, guest_id=guest.id,
        signal_type="phone", value="+922222222222", source="ivr_call",
    )
    db.commit()

    db.refresh(guest)
    assert guest.phone == "+911111111111"


def test_non_phone_signal_type_does_not_touch_guest_phone(db):
    tenant = _make_tenant(db)
    guest = _make_guest(db, tenant.id, phone="")

    identity_service.add_signal(
        db, tenant_id=tenant.id, guest_id=guest.id,
        signal_type="instagram_user_id", value="ig_user_123", source="instagram",
    )
    db.commit()

    db.refresh(guest)
    assert guest.phone == ""
