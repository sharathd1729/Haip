"""Hostaway sync: reproduction and regression tests (Phase 0, workstream D1).

Defects this file pins (found by reading ``sync_hostaway.py`` against ``adapters/pms/hostaway.py``):

1. The task called ``HostawayAdapter(account_id=..., api_secret=...)`` but the adapter's
   constructor took no arguments and read one global account from settings -- a ``TypeError``
   on every run, and per-tenant credentials were never used.
2. The adapter's methods are ``async`` but the task called them synchronously, so even with a
   working constructor ``for listing in listings`` iterated a coroutine.
3. New ``Stay`` rows were created without ``property_id`` (NOT NULL) and, when the reservation had
   no phone, without ``guest_id`` (NOT NULL) -- the flush failed and poisoned the session.

The HTTP boundary (``httpx.AsyncClient``) is faked; everything else is the real adapter and task.
"""
import uuid
from datetime import date

import pytest

from app.models.integration import Integration
from app.models.property import Property, Stay
from app.models.tenant import Tenant


class _Resp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _FakeHostaway:
    """Stands in for ``httpx.AsyncClient``; records the credentials the token call used."""

    token_requests: list = []
    listings: list = []
    reservations: list = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, data=None, **k):
        type(self).token_requests.append(data)
        return _Resp({"access_token": "tok"})

    async def get(self, url, headers=None, **k):
        if "/listings" in url:
            return _Resp({"result": type(self).listings})
        if "/reservations" in url:
            offset = int(url.split("offset=")[1]) if "offset=" in url else 0
            return _Resp({"result": type(self).reservations if offset == 0 else []})
        raise AssertionError(f"unexpected Hostaway call {url}")


def _tenant(db, name="T"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"{name.lower()}-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _connect(db, tenant_id, account_id="acc-tenant", secret="secret-tenant"):
    from app.core.encryption import encrypt_credentials
    db.add(Integration(
        id=str(uuid.uuid4()), tenant_id=tenant_id, kind="hostaway", status="active",
        credentials_kms_blob=encrypt_credentials({"account_id": account_id, "api_secret": secret}),
        config={"sync_listings": True, "sync_reservations": True},
    ))
    db.commit()


@pytest.fixture()
def hostaway(db, monkeypatch):
    """Point the task at the per-test session and fake Hostaway's HTTP API."""
    _FakeHostaway.token_requests = []
    _FakeHostaway.listings = [{"id": 555, "name": "Lake Villa", "propertyType": "villa", "city": "Goa"}]
    _FakeHostaway.reservations = []
    monkeypatch.setattr("app.adapters.pms.hostaway.httpx.AsyncClient", _FakeHostaway)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr("app.workers.tasks.sync_hostaway.SessionLocal", lambda: db)
    return _FakeHostaway


def _run(tenant_id):
    from app.workers.tasks.sync_hostaway import sync_hostaway
    return sync_hostaway.run(tenant_id)


def _reservation(**over):
    res = {
        "id": 9001, "listingMapId": 555, "arrivalDate": "2026-12-20", "departureDate": "2026-12-23",
        "status": "confirmed", "channelName": "airbnb", "totalPrice": 42000,
        "guestName": "Asha Rao", "phone": "+919876500001", "guestEmail": "asha@example.com",
    }
    res.update(over)
    return res


def test_sync_authenticates_with_the_tenants_own_credentials(db, hostaway):
    """Defect 1: the tenant's account id/secret reach Hostaway's token call, not a global one."""
    t = _tenant(db)
    _connect(db, t.id, account_id="acc-A", secret="sec-A")

    result = _run(t.id)

    assert result["status"] == "ok", result
    assert hostaway.token_requests, "the sync never reached Hostaway"
    assert hostaway.token_requests[0]["client_id"] == "acc-A"
    assert hostaway.token_requests[0]["client_secret"] == "sec-A"


def test_sync_creates_property_and_stay_linked_to_it(db, hostaway):
    """Defects 2 and 3: listings become properties; a reservation becomes a Stay with property and guest."""
    t = _tenant(db)
    _connect(db, t.id)
    hostaway.reservations = [_reservation()]

    result = _run(t.id)

    assert result["status"] == "ok", result
    assert result["listings"] == 1 and result["reservations"] == 1
    prop = db.query(Property).filter_by(tenant_id=t.id, hostaway_listing_id="555").one()
    stay = db.query(Stay).filter_by(tenant_id=t.id, hostaway_booking_id="9001").one()
    assert stay.property_id == prop.id
    assert stay.guest_id is not None
    assert stay.check_in == date(2026, 12, 20) and stay.check_out == date(2026, 12, 23)


def test_sync_is_idempotent(db, hostaway):
    t = _tenant(db)
    _connect(db, t.id)
    hostaway.reservations = [_reservation()]

    _run(t.id)
    _run(t.id)

    assert db.query(Stay).filter_by(tenant_id=t.id).count() == 1
    assert db.query(Property).filter_by(tenant_id=t.id).count() == 1


def test_reservation_that_cannot_be_linked_is_skipped_not_fatal(db, hostaway):
    """No phone (no guest to link) or an unknown listing must skip that reservation, count it,
    and still import the good ones -- never invent a guest or a property."""
    t = _tenant(db)
    _connect(db, t.id)
    hostaway.reservations = [
        _reservation(id=1, phone="", guestPhone=""),                 # no guest
        _reservation(id=2, listingMapId=999999),                     # listing we do not have
        _reservation(id=3, phone="+919876500003", guestName="Ok"),   # good
    ]

    result = _run(t.id)

    assert result["status"] == "ok", result
    assert result["reservations"] == 1
    assert result["skipped"] == 2
    assert [s.hostaway_booking_id for s in db.query(Stay).filter_by(tenant_id=t.id)] == ["3"]


def test_sync_never_attaches_to_another_tenants_property(db, hostaway):
    """Tenant isolation: tenant B's reservation for listing 555 must not link to tenant A's property 555."""
    a, b = _tenant(db, "A"), _tenant(db, "B")
    db.add(Property(id=str(uuid.uuid4()), tenant_id=a.id, name="A villa", slug="a-villa", hostaway_listing_id="555"))
    db.commit()
    _connect(db, b.id)
    hostaway.listings = []                                           # B's account has no listings
    hostaway.reservations = [_reservation()]

    result = _run(b.id)

    assert result["reservations"] == 0 and result["skipped"] == 1
    assert db.query(Stay).filter_by(tenant_id=b.id).count() == 0
    assert db.query(Stay).filter_by(tenant_id=a.id).count() == 0
