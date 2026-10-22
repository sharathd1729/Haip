"""Guests are greeted by a real name (22 Oct 2026: a paid booking's WhatsApp said "Namaskara there" while the chat knew him as
Chandu). Placeholders and phone numbers are never names; a booking guest with no name borrows the same number's name."""
import uuid

import pytest

from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity
from app.models.tenant import Tenant
from app.services import guest_names as gn
from app.services import wa_booking_messages as wbm


@pytest.mark.parametrize("name,expected", [
    ("Chandu Rao", "Chandu"), ("  Kiran ", "Kiran"), (None, "there"), ("", "there"), ("Unknown", "there"), ("guest", "there"),
    ("+91 91008 18291", "there"), ("9100818291", "there"), ("-", "there"),
])
def test_placeholders_and_phone_numbers_are_not_names(name, expected):
    assert gn.first_name(name) == expected


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"gn-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.commit()
    return t


def _guest(db, tid, name, phone="+919100818291", signal="phone"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name=name, phone=phone)
    db.add(g)
    db.flush()
    db.add(GuestIdentity(tenant_id=tid, guest_id=g.id, identity_type=signal, identity_value=phone, source="test", confidence=0.9))
    db.commit()
    return g


def test_a_nameless_booking_guest_borrows_the_same_numbers_whatsapp_name(db):
    t = _tenant(db)
    booking_guest = _guest(db, t.id, None)                          # booking form: "phone" signal, no name
    _guest(db, t.id, "Chandu", signal="whatsapp_number")             # the WhatsApp chat: same number, profile name
    assert gn.best_first_name(db, t.id, booking_guest) == "Chandu"
    own = _guest(db, t.id, "Kiran Rao", phone="+919999900000")
    assert gn.best_first_name(db, t.id, own) == "Kiran"
    alone = _guest(db, t.id, "Unknown", phone="+919888800000")
    assert gn.best_first_name(db, t.id, alone) == "there"


def test_names_never_cross_workspaces(db):
    t1, t2 = _tenant(db), _tenant(db)
    booking_guest = _guest(db, t1.id, None)
    _guest(db, t2.id, "Chandu", signal="whatsapp_number")                       # same number, other workspace
    assert gn.best_first_name(db, t1.id, booking_guest) == "there"


def test_whatsapp_profile_fills_only_a_missing_name():
    g = Guest(name=None)
    assert gn.fill_from_profile(g, "Chandu") and g.name == "Chandu"
    assert not gn.fill_from_profile(g, "Someone Else") and g.name == "Chandu"     # a real name is never overwritten
    g2 = Guest(name="+91 91008 18291")
    assert gn.fill_from_profile(g2, "Chandu") and g2.name == "Chandu"
    assert not gn.fill_from_profile(Guest(name=None), "+91 99999 99999")


def test_booking_messages_use_the_borrowed_name(db):
    t = _tenant(db)
    booking_guest = _guest(db, t.id, None)
    _guest(db, t.id, "Chandu", signal="whatsapp_number")

    class _Stay:
        guest = booking_guest
    assert wbm._first(db, t, _Stay()) == "Chandu"
