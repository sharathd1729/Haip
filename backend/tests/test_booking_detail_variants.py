"""Opening a booking from the calendar, dashboard or a lead must load for every shape of booking the calendar can show, and an
unknown, deleted or other-workspace id must be a clean 404 (never a 500, which the page used to present as "not found")."""
import uuid
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.usefixtures("capabilities_seeded")

from app.models.base import gen_uuid  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.property import Property, Stay  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _d(n):
    return date.today() + timedelta(days=n)


def _stay(db, tid, **over):
    prop = db.query(Property).filter_by(tenant_id=tid).first()
    if prop is None:
        prop = Property(id=gen_uuid(), tenant_id=tid, name="Unassigned (vehicle not chosen yet)", slug=f"u-{uuid.uuid4().hex[:6]}", type="caravan", is_active=True)
        db.add(prop)
    g = Guest(id=gen_uuid(), tenant_id=tid, name="Krithika (Brandaid Events)", phone=f"+9199{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    db.flush()
    base = dict(id=gen_uuid(), tenant_id=tid, guest_id=g.id, property_id=prop.id, check_in=_d(3), check_out=_d(5), adults=2, status="confirmed",
                total_amount=10000, channel_source="direct")
    base.update(over)
    s = Stay(**base)
    db.add(s)
    db.commit()
    return s


VARIANTS = {
    "same_day": dict(check_in=_d(3), check_out=_d(3)),
    "no_total": dict(total_amount=None),
    "zero_adults": dict(adults=0, children=None),
    "no_channel": dict(channel_source=None),
    "cancelled": dict(status="cancelled"),
    "past": dict(check_in=_d(-10), check_out=_d(-8)),
    "pms_booking": dict(hostaway_booking_id="HA-123", channel_source="airbnb"),
    "requests_not_a_list": dict(special_requests="late arrival"),
    "no_requests": dict(special_requests=None),
}


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_every_booking_shape_the_calendar_shows_opens(client, db, tenant_and_user, name):
    s = _stay(db, tenant_and_user["tenant"].id, **VARIANTS[name])
    r = client.get(f"/api/v1/bookings/{s.id}", headers=_h(tenant_and_user))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == s.id


def test_unknown_and_other_workspace_ids_are_a_clean_404(client, db, tenant_and_user):
    other = Tenant(id=gen_uuid(), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.flush()
    theirs = _stay(db, other.id)
    for bid in (str(uuid.uuid4()), theirs.id, "not-an-id"):
        r = client.get(f"/api/v1/bookings/{bid}", headers=_h(tenant_and_user))
        assert r.status_code == 404 and r.json()["detail"] == "Booking not found", (bid, r.status_code, r.text)
