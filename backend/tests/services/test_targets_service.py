"""Sales targets: the monthly -> daily division, and target CRUD.

The division maths is the part worth pinning: the owner types ONE
monthly number and every other figure in the module is derived from it,
so an off-by-one in days-elapsed or a rounding shortcut silently
misreports whether the business is ahead or behind.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.models.tenant import Tenant
from app.models.sales_target import SCOPE_AGENT, SCOPE_PROPERTY, SCOPE_TENANT
from app.services import targets_service as ts


def _tenant(db):
    t = Tenant(name="T", slug=f"t-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(t); db.commit()
    return t


# ── division maths ───────────────────────────────────────────────────────

class TestDailyDivision:
    def test_splits_evenly_across_a_31_day_month(self):
        # 6,300,000 / 31 = 203,225.80..., matching the real-world shape of
        # a monthly target that isn't a clean multiple of the day count.
        assert ts.daily_target(Decimal("6300000"), date(2026, 7, 1)) == Decimal("6300000") / Decimal(31)

    def test_uses_the_real_length_of_each_month(self):
        assert ts.days_in_month(date(2026, 2, 1)) == 28   # non-leap
        assert ts.days_in_month(date(2028, 2, 1)) == 29   # leap
        assert ts.days_in_month(date(2026, 4, 1)) == 30
        assert ts.days_in_month(date(2026, 7, 1)) == 31

    def test_daily_x_days_reconciles_exactly_to_the_monthly_figure(self):
        """No rounding drift: the daily target multiplied back out must
        equal the number the owner actually typed, or the last day of the
        month shows a phantom surplus/deficit of a few rupees."""
        monthly = Decimal("6300000")
        m = date(2026, 7, 1)
        assert ts.daily_target(monthly, m) * 31 == monthly

    def test_target_till_date_accumulates_by_day(self):
        monthly = Decimal("3100")  # 100/day across 31 days
        m = date(2026, 7, 1)
        assert ts.target_till_date(monthly, m, date(2026, 7, 1)) == Decimal(100)
        assert ts.target_till_date(monthly, m, date(2026, 7, 10)) == Decimal(1000)
        assert ts.target_till_date(monthly, m, date(2026, 7, 31)) == Decimal(3100)

    def test_before_the_month_is_zero_and_after_is_capped(self):
        """A report run in September against a July target must show
        July's whole number -- never 60/31ths of it."""
        monthly = Decimal("3100")
        m = date(2026, 7, 1)
        assert ts.target_till_date(monthly, m, date(2026, 6, 30)) == Decimal(0)
        assert ts.target_till_date(monthly, m, date(2026, 9, 15)) == Decimal(3100)

    def test_month_start_normalises_any_date_in_the_month(self):
        assert ts.month_start(date(2026, 7, 23)) == date(2026, 7, 1)


# ── CRUD ─────────────────────────────────────────────────────────────────

class TestSetTarget:
    def test_creates_then_updates_in_place(self, db):
        """Re-setting a month's target must edit the row, not add a second
        one -- reports can't choose between two targets for one scope."""
        t = _tenant(db)
        ts.set_target(db, t.id, SCOPE_TENANT, None, date(2026, 7, 1), Decimal("5000000"))
        ts.set_target(db, t.id, SCOPE_TENANT, None, date(2026, 7, 15), Decimal("6300000"))

        rows = ts.list_targets(db, t.id, date(2026, 7, 1))
        assert len(rows) == 1
        assert Decimal(rows[0].target_amount) == Decimal("6300000")

    def test_any_date_in_the_month_hits_the_same_row(self, db):
        t = _tenant(db)
        ts.set_target(db, t.id, SCOPE_TENANT, None, date(2026, 7, 23), Decimal("100"))
        assert ts.get_target(db, t.id, SCOPE_TENANT, None, date(2026, 7, 1)) is not None

    def test_scopes_are_independent(self, db):
        t = _tenant(db)
        m = date(2026, 7, 1)
        ts.set_target(db, t.id, SCOPE_TENANT, None, m, Decimal("6300000"))
        ts.set_target(db, t.id, SCOPE_AGENT, "agent-1", m, Decimal("1400000"))
        ts.set_target(db, t.id, SCOPE_PROPERTY, "prop-1", m, Decimal("3000000"))
        assert len(ts.list_targets(db, t.id, m)) == 3

    def test_rejects_a_bad_scope_type(self, db):
        t = _tenant(db)
        with pytest.raises(ValueError):
            ts.set_target(db, t.id, "region", "x", date(2026, 7, 1), Decimal("1"))

    def test_rejects_scoped_target_with_no_scope_id(self, db):
        t = _tenant(db)
        with pytest.raises(ValueError):
            ts.set_target(db, t.id, SCOPE_AGENT, None, date(2026, 7, 1), Decimal("1"))

    def test_rejects_tenant_target_carrying_a_scope_id(self, db):
        t = _tenant(db)
        with pytest.raises(ValueError):
            ts.set_target(db, t.id, SCOPE_TENANT, "someone", date(2026, 7, 1), Decimal("1"))

    def test_rejects_negative_amount(self, db):
        t = _tenant(db)
        with pytest.raises(ValueError):
            ts.set_target(db, t.id, SCOPE_TENANT, None, date(2026, 7, 1), Decimal("-5"))

    def test_tenant_isolation(self, db):
        """One tenant's targets must never appear in another's list."""
        a, b = _tenant(db), _tenant(db)
        m = date(2026, 7, 1)
        ts.set_target(db, a.id, SCOPE_TENANT, None, m, Decimal("6300000"))
        assert len(ts.list_targets(db, a.id, m)) == 1
        assert ts.list_targets(db, b.id, m) == []

    def test_delete(self, db):
        t = _tenant(db)
        m = date(2026, 7, 1)
        ts.set_target(db, t.id, SCOPE_TENANT, None, m, Decimal("1"))
        assert ts.delete_target(db, t.id, SCOPE_TENANT, None, m) is True
        assert ts.delete_target(db, t.id, SCOPE_TENANT, None, m) is False
        assert ts.list_targets(db, t.id, m) == []
