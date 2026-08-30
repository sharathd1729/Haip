"""Revenue vs target, read from real booking data.

The two things worth pinning hardest:
  1. Agent attribution runs Stay -> Inquiry.assigned_to. Revenue that
     can't be credited to a person must surface as "unattributed", never
     be dropped -- otherwise the agent rows quietly stop reconciling to
     the tenant total.
  2. booked-on (Stay.created_at) and stay-date (Stay.check_in) are
     different axes. Pick-up uses the first; the month split and forward
     holding use the second. Mixing them double-counts.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.property import Property, Stay
from app.models.sales_target import SCOPE_AGENT, SCOPE_PROPERTY, SCOPE_TENANT
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import sales_performance_service as sps
from app.services import targets_service as ts


JULY = date(2026, 7, 1)


def _tenant(db):
    t = Tenant(name="T", slug=f"t-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(t); db.commit()
    return t


def _agent(db, t, name, role=UserRole.RESERVATIONS):
    from app.core.security import get_password_hash
    u = User(
        id=str(uuid.uuid4()), tenant_id=t.id, name=name,
        email=f"{name.lower()}-{uuid.uuid4().hex[:6]}@t.com",
        hashed_password=get_password_hash("x123456789"), role=role, is_active=True,
    )
    db.add(u); db.commit()
    return u


def _prop(db, t, name):
    p = Property(id=str(uuid.uuid4()), tenant_id=t.id, name=name, slug=name.lower().replace(" ", "-"), type="caravan")
    db.add(p); db.commit()
    return p


def _stay(db, t, *, prop, amount, booked_on, check_in, agent=None, status="confirmed"):
    """A booking. `agent` wires the real attribution path the product
    uses: inquiry_service sets Stay.inquiry_id on a closed-won lead, and
    the inquiry carries assigned_to."""
    g = Guest(tenant_id=t.id, name="G")
    db.add(g); db.flush()

    inq_id = None
    if agent is not None:
        inq = Inquiry(tenant_id=t.id, guest_id=g.id, assigned_to=agent.id)
        db.add(inq); db.flush()
        inq_id = inq.id

    s = Stay(
        id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, property_id=prop.id,
        inquiry_id=inq_id, check_in=check_in, check_out=check_in,
        status=status, total_amount=Decimal(amount), currency="INR",
        created_at=datetime.combine(booked_on, datetime.min.time(), tzinfo=timezone.utc),
    )
    db.add(s); db.commit()
    return s


# ── pick-up ──────────────────────────────────────────────────────────────

class TestPickupReport:
    def test_one_row_per_day_with_cumulative_target(self, db):
        t = _tenant(db)
        ts.set_target(db, t.id, SCOPE_TENANT, None, JULY, Decimal("3100"))  # 100/day
        r = sps.pickup_report(db, t.id, JULY, as_of=date(2026, 7, 31))

        assert len(r["rows"]) == 31
        assert r["rows"][0]["target_till_date"] == 100
        assert r["rows"][9]["target_till_date"] == 1000
        assert r["rows"][30]["target_till_date"] == 3100

    def test_pickup_is_keyed_on_when_the_booking_was_made(self, db):
        """A stay booked on 3 Jul for an October trip is 3 July's pick-up,
        not October's."""
        t = _tenant(db)
        p = _prop(db, t, "Black Caravan")
        ts.set_target(db, t.id, SCOPE_TENANT, None, JULY, Decimal("3100"))
        _stay(db, t, prop=p, amount=500, booked_on=date(2026, 7, 3), check_in=date(2026, 10, 5))

        r = sps.pickup_report(db, t.id, JULY, as_of=date(2026, 7, 31))
        assert r["rows"][2]["pickup_of_day"] == 500
        assert r["picked_up"] == 500

    def test_month_split_uses_the_stay_date(self, db):
        t = _tenant(db)
        p = _prop(db, t, "White Caravan")
        booked = date(2026, 7, 10)
        _stay(db, t, prop=p, amount=100, booked_on=booked, check_in=date(2026, 7, 20))   # this month
        _stay(db, t, prop=p, amount=200, booked_on=booked, check_in=date(2026, 8, 20))   # next month
        _stay(db, t, prop=p, amount=300, booked_on=booked, check_in=date(2026, 12, 1))   # future

        r = sps.pickup_report(db, t.id, JULY, as_of=date(2026, 7, 31))
        assert r["split"] == {"this_month": 100.0, "next_month": 200.0, "future": 300.0}
        # and the three still sum to the day's total pick-up
        assert r["rows"][9]["pickup_of_day"] == 600

    def test_variance_is_none_for_days_that_have_not_happened(self, db):
        """A future day isn't 'in deficit' -- it hasn't occurred."""
        t = _tenant(db)
        ts.set_target(db, t.id, SCOPE_TENANT, None, JULY, Decimal("3100"))
        r = sps.pickup_report(db, t.id, JULY, as_of=date(2026, 7, 10))
        assert r["rows"][9]["variance"] is not None
        assert r["rows"][10]["variance"] is None
        assert r["rows"][10]["is_future"] is True

    def test_cancelled_bookings_are_not_revenue(self, db):
        t = _tenant(db)
        p = _prop(db, t, "Black Caravan")
        _stay(db, t, prop=p, amount=999, booked_on=date(2026, 7, 5), check_in=date(2026, 7, 6), status="cancelled")
        r = sps.pickup_report(db, t.id, JULY, as_of=date(2026, 7, 31))
        assert r["picked_up"] == 0

    def test_reports_cleanly_when_no_target_is_set(self, db):
        """The module must not explode before the owner has entered
        anything -- it should just say so."""
        t = _tenant(db)
        r = sps.pickup_report(db, t.id, JULY, as_of=date(2026, 7, 31))
        assert r["has_target"] is False
        assert r["monthly_target"] == 0
        assert r["achieved_pct"] is None
        assert len(r["rows"]) == 31

    def test_tenant_isolation(self, db):
        a, b = _tenant(db), _tenant(db)
        pa = _prop(db, a, "A caravan")
        _stay(db, a, prop=pa, amount=5000, booked_on=date(2026, 7, 4), check_in=date(2026, 7, 5))
        assert sps.pickup_report(db, b.id, JULY, as_of=date(2026, 7, 31))["picked_up"] == 0


# ── agents ───────────────────────────────────────────────────────────────

class TestAgentPerformance:
    def test_credits_revenue_via_inquiry_assigned_to(self, db):
        t = _tenant(db)
        p = _prop(db, t, "Black Caravan")
        jishanth = _agent(db, t, "Jishanth")
        krisha = _agent(db, t, "Krisha")
        ts.set_target(db, t.id, SCOPE_AGENT, jishanth.id, JULY, Decimal("1000"))

        _stay(db, t, prop=p, amount=1200, booked_on=date(2026, 7, 4), check_in=date(2026, 7, 6), agent=jishanth)
        _stay(db, t, prop=p, amount=400, booked_on=date(2026, 7, 8), check_in=date(2026, 7, 9), agent=krisha)

        r = sps.agent_performance(db, t.id, JULY)
        by_name = {a["name"]: a for a in r["agents"]}
        assert by_name["Jishanth"]["revenue"] == 1200
        assert by_name["Jishanth"]["target"] == 1000
        assert by_name["Jishanth"]["achieved_pct"] == 120
        assert by_name["Krisha"]["revenue"] == 400
        assert by_name["Krisha"]["achieved_pct"] is None  # no target set

    def test_unattributed_revenue_is_reported_not_dropped(self, db):
        """A stay with no inquiry (manual booking, channel import) is real
        money -- it must still reconcile into the total."""
        t = _tenant(db)
        p = _prop(db, t, "Black Caravan")
        jishanth = _agent(db, t, "Jishanth")
        _stay(db, t, prop=p, amount=1000, booked_on=date(2026, 7, 4), check_in=date(2026, 7, 6), agent=jishanth)
        _stay(db, t, prop=p, amount=250, booked_on=date(2026, 7, 5), check_in=date(2026, 7, 7))  # no agent

        r = sps.agent_performance(db, t.id, JULY)
        assert r["unattributed"] == 250
        assert r["total_revenue"] == 1250

    def test_agents_with_no_sales_still_appear(self, db):
        """A zero month is information -- the agent shouldn't vanish."""
        t = _tenant(db)
        _agent(db, t, "Krisha")
        r = sps.agent_performance(db, t.id, JULY)
        assert [a["name"] for a in r["agents"]] == ["Krisha"]
        assert r["agents"][0]["revenue"] == 0

    def test_owner_is_not_measured_as_a_selling_agent(self, db):
        t = _tenant(db)
        _agent(db, t, "Rathaa", role=UserRole.OWNER)
        _agent(db, t, "Krisha")
        r = sps.agent_performance(db, t.id, JULY)
        assert [a["name"] for a in r["agents"]] == ["Krisha"]

    def test_sorted_by_revenue_descending(self, db):
        t = _tenant(db)
        p = _prop(db, t, "C")
        low = _agent(db, t, "Low")
        high = _agent(db, t, "High")
        _stay(db, t, prop=p, amount=100, booked_on=date(2026, 7, 2), check_in=date(2026, 7, 3), agent=low)
        _stay(db, t, prop=p, amount=900, booked_on=date(2026, 7, 2), check_in=date(2026, 7, 3), agent=high)
        r = sps.agent_performance(db, t.id, JULY)
        assert [a["name"] for a in r["agents"]] == ["High", "Low"]


# ── properties ───────────────────────────────────────────────────────────

class TestPropertyPerformance:
    def test_revenue_and_target_per_property(self, db):
        t = _tenant(db)
        black = _prop(db, t, "Black Caravan")
        white = _prop(db, t, "White Caravan")
        ts.set_target(db, t.id, SCOPE_PROPERTY, black.id, JULY, Decimal("1000"))

        _stay(db, t, prop=black, amount=1500, booked_on=date(2026, 7, 3), check_in=date(2026, 7, 4))
        _stay(db, t, prop=white, amount=700, booked_on=date(2026, 7, 3), check_in=date(2026, 7, 4))

        r = sps.property_performance(db, t.id, JULY)
        by_name = {p["name"]: p for p in r["properties"]}
        assert by_name["Black Caravan"]["revenue"] == 1500
        assert by_name["Black Caravan"]["achieved_pct"] == 150
        assert by_name["White Caravan"]["revenue"] == 700
        assert r["total_revenue"] == 2200

    def test_holding_counts_next_month_stays_whenever_booked(self, db):
        """Holding is a forward-looking number keyed on check-in, so a
        booking made back in June for August still shows as August holding
        -- but must NOT count toward July's revenue."""
        t = _tenant(db)
        p = _prop(db, t, "Black Caravan")
        _stay(db, t, prop=p, amount=800, booked_on=date(2026, 6, 20), check_in=date(2026, 8, 10))

        r = sps.property_performance(db, t.id, JULY)
        row = r["properties"][0]
        assert row["holding_next_month"] == 800
        assert row["revenue"] == 0
        assert r["total_holding"] == 800
