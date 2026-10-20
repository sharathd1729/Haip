"""Rate calculator pricing (services/rate_calculator.py): GST inclusive vs on top at 0/5/18/40/custom, add-on units, discount,
price override and when it needs an owner's OK, the fixed-package and custom-trip bases from the tenant's own records, and the
exact WhatsApp text. No database writes happen here."""
from datetime import timedelta
from decimal import Decimal as D

import pytest

from app.models.tenant import Tenant
from app.schemas.quote_calculator import CalcIn
from app.services import quote_calc_catalog as cat
from app.services import rate_calculator as rc
from tests.test_business_data import TODAY
from tests.test_quote_builder_pricing import ratha

START = TODAY + timedelta(days=12)


def tot(subtotal, *, d="0", r="18", inc=True, ov=None, adv="50", th="10", maxd="10"):
    return rc.totals(D(subtotal), discount_percent=D(d), gst_percent=D(r), inclusive=inc, override=D(ov) if ov else None,
                     advance_percent=D(adv), threshold=D(th), max_discount=D(maxd))


@pytest.mark.parametrize("rate,inc_gst,exc_gst", [
    ("0", "0", "0"), ("5", "4762", "5000"), ("18", "15254", "18000"), ("40", "28571", "40000"), ("12", "10714", "12000"),
])
def test_gst_inside_or_on_top(rate, inc_gst, exc_gst):
    inside = tot("100000", r=rate, inc=True)
    assert inside["gst"] == D(inc_gst) and inside["total"] == D("100000") and inside["taxable"] == D("100000") - D(inc_gst)
    on_top = tot("100000", r=rate, inc=False)
    assert on_top["gst"] == D(exc_gst) and on_top["total"] == D("100000") + D(exc_gst) and on_top["taxable"] == D("100000")


def test_discount_applies_to_everything_and_the_advance_to_the_final_total():
    t = tot("75000", d="10", r="18", inc=False)
    assert (t["discount"], t["net"], t["gst"], t["total"], t["advance"]) == (D("7500"), D("67500"), D("12150"), D("79650"), D("39825"))
    assert t["needs_approval"] is False


def test_a_discount_above_the_limit_needs_approval():
    t = tot("75000", d="15", maxd="10")
    assert t["needs_approval"] and "15% discount" in t["approval_reasons"][0]


@pytest.mark.parametrize("override,below,needs", [("80000", "-6.7", False), ("68250", "9.0", False), ("67400", "10.1", True)])
def test_override_inclusive(override, below, needs):
    t = tot("75000", ov=override)
    assert t["overridden"] and t["total"] == D(override) and t["below_percent"] == D(below) and t["needs_approval"] is needs
    assert t["suggested_total"] == D("75000") and t["advance"] == rc.rupee(D(override) / 2)


def test_override_before_gst_adds_gst_on_the_new_price():
    t = tot("75000", inc=False, ov="60000")
    assert (t["taxable"], t["gst"], t["total"], t["suggested_total"]) == (D("60000"), D("10800"), D("70800"), D("88500"))
    assert t["below_percent"] == D("20.0") and t["needs_approval"]


def test_override_equal_to_the_suggested_price_is_no_override():
    t = tot("75000", ov="75000")
    assert not t["overridden"] and t["override_price"] is None


def test_the_threshold_is_the_tenants():
    assert tot("100000", ov="85000", th="20")["needs_approval"] is False
    assert tot("100000", ov="85000", th="10")["needs_approval"] is True


@pytest.mark.parametrize("unit,qty", [("one_time", 1), ("per_day", 3), ("per_guest", 5), ("per_guest_day", 15)])
def test_addon_units(unit, qty):
    assert rc.addon_quantity(unit, 3, 5) == qty


# ─── against Ratha's records ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def r(db):
    return ratha(db)


def calc(db, w, **kw):
    t = db.query(Tenant).filter_by(id=w.t.id).first()
    body = CalcIn(**{"mode": "fixed", "package_key": "day-rate", "start_date": START, "days": 2, "guests": 5, **kw})
    return rc.compute(db, t, body), body


def test_fixed_day_package_prices_each_day_plus_extra_guests(db, r):
    c, _ = calc(db, r)
    assert c.ok and [(ln["label"], ln["amount"]) for ln in c.lines] == [("Day rate × 2 days", D("50000.00")), ("Extra guests × 1", D("5000.00"))]
    assert c.t["subtotal"] == D("55000.00") and c.check_out == START + timedelta(days=2)


def test_flat_package_and_per_trip_extra_guest(db, r):
    c, _ = calc(db, r, package_key="coorg-48", guests=7)
    assert [(ln["label"], ln["amount"]) for ln in c.lines] == [("Coorg 48-hour Retreat", D("70000.00")), ("Extra guests × 1", D("2500.00"))]


def test_levels_are_separate_packages(db, r):
    keys = [p["key"] for p in cat.packages(db, r.t.id, TODAY)["packages"]]
    assert "all-inclusive::40000" in keys and "all-inclusive" not in keys
    c, _ = calc(db, r, package_key="all-inclusive::40000", guests=4)
    assert c.ok and c.lines[0]["amount"] == D("80000.00") and "Level 40k" in c.title


def test_custom_trip_uses_the_day_rate_terms(db, r):
    c, _ = calc(db, r, mode="custom", package_key=None, custom={"title": "Coorg + KRS", "rate_per_day": "25000", "planned_km": "560",
                                                                 "km_rate": "90"})
    assert [(ln["label"], ln["amount"]) for ln in c.lines] == [
        ("Coorg + KRS × 2 days", D("50000.00")), ("Extra guests × 1", D("5000.00")), ("Extra 60 km at ₹90", D("5400.00"))]
    rules = cat.custom_rules(db, db.query(Tenant).filter_by(id=r.t.id).first(), TODAY)
    assert rules["km_rates"] == [D("100"), D("90"), D("80"), D("70"), D("60")] and rules["free_guests"] == 4


def test_addons_and_unknown_package(db, r):
    c, _ = calc(db, r, addons=[{"name": "Culinary kit", "price": "5000", "unit": "one_time"},
                               {"name": "Breakfast", "price": "450", "unit": "per_guest_day"}])
    assert c.lines[-1] == {"label": "Breakfast × 5 guests × 2 days", "amount": D("4500.00"), "detail": "per_guest_day", "kind": "addon"}
    bad, _ = calc(db, r, package_key="nope")
    assert not bad.ok and "not published" in bad.message


def test_message_matches_the_mock_up_shape(db, r):
    c, body = calc(db, r, package_key="coorg-48", gst_percent="18", prices_include_gst=True, override={"price": "70000", "show_usual": True})
    snap = rc.to_snapshot(c, body)
    text = rc.render_message(snap, guest_name="Kiran Reddy", brand="Ratha", greeting="Namaskara", pay_url="https://rzp.io/i/x")
    lines = text.split("\n")
    assert lines[0] == "Namaskara Kiran, here is your Ratha plan." and lines[2] == "Coorg 48-hour Retreat"
    assert "noon to" in lines[3] and lines[3].endswith("· 5 guests")
    assert "• Coorg 48-hour Retreat: ₹70,000" in text and "• Extra guests" not in text
    assert "Total ₹70,000 (incl. GST ₹10,678)" in text and "Advance ₹35,000 to confirm" in text
    assert "Pay the advance here: https://rzp.io/i/x" in text and text.endswith("Tolls and parking at actuals. Valid for 3 days.")


def test_message_with_gst_on_top_and_a_lowered_price(db, r):
    c, body = calc(db, r, gst_percent="5", prices_include_gst=False, override={"price": "50000", "show_usual": True})
    snap = rc.to_snapshot(c, body)
    text = rc.render_message(snap, guest_name=None, brand="Ratha", greeting="Namaskara", pay_url=None)
    assert text.startswith("Namaskara there,") and "Usual price ~₹55,000~ + GST\nYour price ₹50,000 + GST ₹2,500 = ₹52,500" in text
    assert "Pay the advance" not in text and snap["override"]["below_percent"] == "9.1"
