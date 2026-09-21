"""Caravan rate-plan selection: _resolve_rate()/search() picking between a
property's several RatePlan rows by the guest's requested duration
(same_day / overnight / multiday) instead of an unordered `.first()`.

Confirmed live bug this fixes: Ratha's two caravans each carry 3 active
RatePlan rows (One-Day ~25000, Overnight ~42000, Multi-Day ~0) with no
selection logic distinguishing them -- any quote could silently resolve to
any of the 3, including the ₹0 one. See migration 087 / calculator_service.py.
"""
import uuid

import pytest

from tests.conftest import *  # noqa: F401,F403

from app.models.tenant import Tenant
from app.models.property import Property, RatePlan
from app.services.calculator_service import calculator_service


def _make_tenant(db):
    tenant = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant); db.commit()
    return tenant


def _make_caravan(db, tenant, with_plans=("same_day", "overnight", "multiday")):
    prop = Property(
        id=str(uuid.uuid4()), tenant_id=tenant.id, name="White Caravan",
        slug=f"caravan-{uuid.uuid4().hex[:6]}", type="caravan",
        max_adults=8, price_per_day=24000, price_per_km=70,
    )
    db.add(prop); db.commit()

    prices = {"same_day": 25000, "overnight": 42000, "multiday": 0}
    for dt in with_plans:
        db.add(RatePlan(
            id=str(uuid.uuid4()), tenant_id=tenant.id, property_id=prop.id,
            name=f"{dt} plan", base_price_per_night=prices[dt],
            duration_type=dt, is_active=True,
        ))
    db.commit()
    return prop


def _make_villa(db, tenant):
    prop = Property(
        id=str(uuid.uuid4()), tenant_id=tenant.id, name="Garden Villa",
        slug=f"villa-{uuid.uuid4().hex[:6]}", type="villa", max_adults=4,
    )
    db.add(prop); db.commit()
    db.add(RatePlan(
        id=str(uuid.uuid4()), tenant_id=tenant.id, property_id=prop.id,
        name="Standard Rate", base_price_per_night=8000, is_active=True,
    ))
    db.commit()
    return prop


class TestCaravanDurationBuckets:
    def test_same_day_request_picks_same_day_plan(self, db):
        tenant = _make_tenant(db)
        prop = _make_caravan(db, tenant)

        results = calculator_service.search(
            db, tenant_id=tenant.id, checkin="2026-12-10", checkout="2026-12-10",
            adults=4, property_id=prop.id,
        )
        assert len(results) == 1
        assert results[0].price_per_night == 25000
        assert results[0].rate_name == "same_day plan"
        assert results[0].nights == 0
        assert results[0].subtotal_accommodation == 25000  # max(nights, 1) billing

    def test_overnight_request_picks_overnight_plan(self, db):
        tenant = _make_tenant(db)
        prop = _make_caravan(db, tenant)

        results = calculator_service.search(
            db, tenant_id=tenant.id, checkin="2026-12-10", checkout="2026-12-11",
            adults=4, property_id=prop.id,
        )
        assert len(results) == 1
        assert results[0].price_per_night == 42000
        assert results[0].rate_name == "overnight plan"

    def test_multiday_request_picks_multiday_plan(self, db):
        tenant = _make_tenant(db)
        prop = _make_caravan(db, tenant)

        results = calculator_service.search(
            db, tenant_id=tenant.id, checkin="2026-12-10", checkout="2026-12-12",
            adults=4, property_id=prop.id,
        )
        assert len(results) == 1
        assert results[0].price_per_night == 0
        assert results[0].rate_name == "multiday plan"

    def test_no_matching_bucket_falls_back_to_price_per_day(self, db):
        """Only a same_day plan configured -- an overnight request must not
        grab it (the old unordered-.first() bug), it should fall through to
        Property.price_per_day instead."""
        tenant = _make_tenant(db)
        prop = _make_caravan(db, tenant, with_plans=("same_day",))

        results = calculator_service.search(
            db, tenant_id=tenant.id, checkin="2026-12-10", checkout="2026-12-11",
            adults=4, property_id=prop.id,
        )
        assert len(results) == 1
        assert results[0].price_per_night == 24000  # price_per_day, not the same_day plan's 25000
        assert results[0].rate_name == "Base rate"

    def test_build_quote_same_day_produces_nonzero_total(self, db):
        tenant = _make_tenant(db)
        prop = _make_caravan(db, tenant)

        quote = calculator_service.build_quote(
            db, tenant_id=tenant.id, property_id=prop.id,
            checkin="2026-12-10", checkout="2026-12-10", adults=4,
        )
        assert quote is not None
        assert quote.subtotal == 25000
        assert quote.total > 0


class TestVillaUnaffected:
    def test_villa_same_day_request_still_returns_nothing(self, db):
        """Pre-existing behaviour for non-caravan properties: a same-day
        "stay" isn't a real booking and must still resolve to no rate,
        exactly like search()'s old blanket `nights <= 0: return []`."""
        tenant = _make_tenant(db)
        _make_villa(db, tenant)

        results = calculator_service.search(
            db, tenant_id=tenant.id, checkin="2026-12-10", checkout="2026-12-10", adults=2,
        )
        assert results == []

    def test_villa_normal_stay_unaffected(self, db):
        tenant = _make_tenant(db)
        prop = _make_villa(db, tenant)

        results = calculator_service.search(
            db, tenant_id=tenant.id, checkin="2026-12-10", checkout="2026-12-12", adults=2,
        )
        assert len(results) == 1
        assert results[0].price_per_night == 8000
        assert results[0].subtotal_accommodation == 16000  # 8000 * 2 nights, unchanged


class TestCapacityCountsAdultsOnly:
    """max_adults caps ADULTS; children have their own max_children.

    Confirmed live on Ratha: 8 adults + 1 toddler was refused by an 8-adult
    caravan because the check compared adults + children against max_adults,
    and the concierge then told the guest the limit was "8 in total,
    regardless of age". The schema always carried max_children separately.
    """

    def _search(self, db, tenant, prop, adults, children=0):
        return calculator_service.search(
            db, tenant_id=tenant.id, checkin="2026-12-10", checkout="2026-12-11",
            adults=adults, children=children, property_id=prop.id,
        )

    def test_eight_adults_plus_a_toddler_fits_an_eight_adult_caravan(self, db):
        tenant = _make_tenant(db)
        prop = _make_caravan(db, tenant)
        assert len(self._search(db, tenant, prop, adults=8, children=1)) == 1

    def test_nine_adults_still_does_not_fit(self, db):
        """Loosening children must not loosen the adult limit."""
        tenant = _make_tenant(db)
        prop = _make_caravan(db, tenant)
        assert self._search(db, tenant, prop, adults=9) == []

    def test_unset_max_children_does_not_forbid_children(self, db):
        """max_children defaults to 0 -- that means 'not configured', not
        'no children allowed'."""
        tenant = _make_tenant(db)
        prop = _make_caravan(db, tenant)
        assert prop.max_children in (0, None)
        assert len(self._search(db, tenant, prop, adults=2, children=3)) == 1

    def test_configured_max_children_is_enforced(self, db):
        tenant = _make_tenant(db)
        prop = _make_caravan(db, tenant)
        prop.max_children = 2
        db.commit()
        assert len(self._search(db, tenant, prop, adults=4, children=2)) == 1
        assert self._search(db, tenant, prop, adults=4, children=3) == []

    def test_villa_adult_limit_unchanged(self, db):
        tenant = _make_tenant(db)
        prop = _make_villa(db, tenant)
        assert len(self._search(db, tenant, prop, adults=4)) == 1
        assert self._search(db, tenant, prop, adults=5) == []
