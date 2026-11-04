"""POST /calculator/dynamic-price takes its base rate from the same resolver as the Calculator page.

It used to fall back to prop.base_price_per_night (a RatePlan column; Property has none), so any stay not covered by one
season end to end answered 500.
"""

import uuid

from app.models.property import Property
from app.models.user import UserRole
from tests.test_business_data import _tenant
from tests.test_increment1_defect_specs import _h, _user

URL = "/api/v1/calculator/dynamic-price"


def _caravan(db, tenant_id, price=None):
    p = Property(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name="Ratha 1",
        slug=f"r-{uuid.uuid4().hex[:6]}",
        type="caravan",
        price_per_day=price,
    )
    db.add(p)
    db.commit()
    return p


def test_no_season_uses_the_property_day_price(client, db):
    t = _tenant(db)
    p = _caravan(db, t.id, price=20000)
    body = {"property_id": p.id, "checkin": "2026-12-10", "checkout": "2026-12-12"}
    res = client.post(URL, json=body, headers=_h(_user(db, t.id, UserRole.OWNER)))
    assert res.status_code == 200, res.text
    assert res.json()["base_rate"] == 20000


def test_no_rate_at_all_is_a_clear_422(client, db):
    t = _tenant(db)
    p = _caravan(db, t.id)
    body = {"property_id": p.id, "checkin": "2026-12-10", "checkout": "2026-12-12"}
    assert client.post(URL, json=body, headers=_h(_user(db, t.id, UserRole.OWNER))).status_code == 422


def test_another_workspaces_property_is_not_found(client, db):
    a, b = _tenant(db), _tenant(db)
    p = _caravan(db, a.id, price=20000)
    body = {"property_id": p.id, "checkin": "2026-12-10", "checkout": "2026-12-12"}
    assert client.post(URL, json=body, headers=_h(_user(db, b.id, UserRole.OWNER))).status_code == 404
