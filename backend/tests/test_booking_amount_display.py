"""Booking money must read right on cancelled and unpriced bookings.

Seen live: a cancelled booking showed "₹10,000 deposit pending" and "₹5 overdue"; a booking from a calendar feed
with no price showed total ₹0 "unpaid".
"""

import pytest

from app.services import booking_service as bsvc
from app.services.booking_service import payment_status
from tests.test_booking_extras import _d, _h, _setup

pytestmark = pytest.mark.usefixtures("capabilities_seeded")


def test_payment_status_without_a_price_is_not_set():
    assert payment_status(0, 0) == "not_set"
    assert payment_status(1000, 0) == "unpaid"
    assert payment_status(1000, 400) == "partial"
    assert payment_status(1000, 1000) == "paid"


def test_cancelled_booking_shows_no_overdue_and_no_pending_deposit(client, db, tenant_and_user):
    _, _, stay = _setup(db, tenant_and_user, total=10)
    h = _h(tenant_and_user)
    items = [
        {"label": "Advance", "amount": 5, "due_date": _d(-3).isoformat()},
        {"label": "Balance", "amount": 5, "due_date": _d(5).isoformat()},
    ]
    assert client.put(f"/api/v1/bookings/{stay.id}/schedule", json={"items": items}, headers=h).status_code == 200
    assert client.put(f"/api/v1/bookings/{stay.id}/deposit", json={"amount": 10000}, headers=h).status_code == 200
    before = client.get(f"/api/v1/bookings/{stay.id}", headers=h).json()
    assert before["next_due"]["overdue"] is True and before["deposit"]["status"] == "pending"

    stay.status = "cancelled"
    db.commit()
    d = client.get(f"/api/v1/bookings/{stay.id}", headers=h).json()
    assert [s["status"] for s in d["schedule"]] == ["cancelled", "cancelled"]
    assert d["next_due"] is None
    assert d["deposit"] is None

    row = client.get("/api/v1/bookings", headers=h).json()["data"][0]
    assert row["payment_overdue"] is False and row["next_payment_amount"] == 0 and row["deposit"] is None


def test_cancelled_booking_still_shows_a_collected_deposit(client, db, tenant_and_user):
    """A deposit actually held may have to be handed back: it stays visible."""
    _, _, stay = _setup(db, tenant_and_user)
    h = _h(tenant_and_user)
    client.put(
        f"/api/v1/bookings/{stay.id}/deposit", json={"amount": 5000, "status": "held", "method": "upi"}, headers=h
    )
    stay.status = "cancelled"
    db.commit()
    assert client.get(f"/api/v1/bookings/{stay.id}", headers=h).json()["deposit"]["status"] == "held"
    assert bsvc.shown_deposit("confirmed", {"status": "pending"}) == {"status": "pending"}


def test_unpriced_booking_reads_amount_not_set_and_is_not_in_the_unpaid_filter(client, db, tenant_and_user):
    _, _, stay = _setup(db, tenant_and_user, total=0, channel="ical")
    h = _h(tenant_and_user)
    d = client.get(f"/api/v1/bookings/{stay.id}", headers=h).json()
    assert d["financials"]["payment_status"] == "not_set"
    assert client.get("/api/v1/bookings", headers=h).json()["data"][0]["payment_status"] == "not_set"
    assert client.get("/api/v1/bookings", params={"payment_status": "unpaid"}, headers=h).json()["meta"]["total"] == 0
