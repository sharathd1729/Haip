"""Ratha's quote-builder pricing rules, with the owner-confirmed numbers (Oct 2026 terms).

  * Day rate: 25,000 a day + GST, 4 guests included, 250 km a day, extra guest 2,500 (a day here; the unit is configurable),
    extra km at the agent's rate between 100 and 60 (a ladder only suggests), tolls and parking at actuals, outside the total;
  * Coorg 48-hour Retreat: 70,000 flat, 6 guests, 480 km, extra guest 2,500 per trip, extra hour 2,000, extra km 70, Coorg only;
  * All-inclusive: day rate by level (35k / 40k / 45k) with the experience kits included;
  * Travel only: 15,000 a day, at least 3 days, no kilometre charge;
  * Reseller: commission 7.5-11.5 % of the pre-tax billing, at least 2 days and 50,000 before tax;
  * planned km = the route's stop distances + the sights the guest adds; a day trip (0 nights) is billed 1 day;
  * a draft route can be previewed but not issued. GST 12 % is the package's placeholder (still to be confirmed by Ratha).
"""
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app.models.property import Property
from app.schemas.business_data import canonical, validate_data
from app.services import business_data_service as bds
from app.services import package_pricing_service as pps
from app.services import quote_service as qs
from tests.test_business_data import TODAY, _workspace

START = TODAY + timedelta(days=12)
KITS = [{"name": n, "kind": "experience", "amount": "5000", "unit": "per_stay"} for n in ("Culinary", "Wellness", "Entertainment", "Adventure")]
LADDER = {"max_per_km": "100", "min_per_km": "60", "ladder": [
    {"up_to_extra_km": 100, "per_km": "100"}, {"up_to_extra_km": 200, "per_km": "90"}, {"up_to_extra_km": 300, "per_km": "80"},
    {"up_to_extra_km": 400, "per_km": "70"}, {"per_km": "60"}]}


def _rate(label, amount, unit="day", **kw):
    return {"label": label, "valid_from": TODAY.isoformat(), "valid_to": (TODAY + timedelta(days=400)).isoformat(), "amount": amount, "unit": unit, **kw}


def day_rate(**over):
    d = {"name": "Day rate", "product": "multiday", "max_guests": 8, "day_count": "noon_to_noon", "rates": [_rate("Day rate", "25000")],
         "extra_guest_charge": {"free_guests": 4, "per_guest": "2500", "unit": "day"}, "included_km_per_day": 250,
         "extra_km_charge": LADDER, "charges": KITS, "at_actuals": ["Tolls and parking"], "inclusions": ["Fuel up to 250 km a day", "Driver and helper"],
         "exclusions": ["Tolls and parking"], "gst_percent": "12", "quote_valid_days": 3}
    d.update(over)
    return d


def coorg_48(**over):
    d = {"name": "Coorg 48-hour Retreat", "product": "route", "max_guests": 8, "min_nights": 2, "max_nights": 2, "duration_hours": 48,
         "day_count": "noon_to_noon", "rates": [_rate("48 hours", "70000", unit="package")],
         "extra_guest_charge": {"free_guests": 6, "per_guest": "2500", "unit": "trip"}, "included_km": 480,
         "extra_km_charge": {"per_km": "70"}, "extra_hour_charge": {"per_hour": "2000"}, "charges": KITS, "destination_keys": ["coorg"],
         "at_actuals": ["Tolls and parking"], "gst_percent": "12"}
    d.update(over)
    return d


def all_inclusive():
    return day_rate(name="All-inclusive", kits_included=True,
                    rates=[_rate("Level 35k", "35000", level="35000"), _rate("Level 40k", "40000", level="40000"), _rate("Level 45k", "45000", level="45000")])


def travel_only():
    return {"name": "Travel only", "product": "multiday", "max_guests": 8, "day_count": "noon_to_noon", "min_days": 3,
            "rates": [_rate("Caravan only", "15000")], "inclusions": ["Caravan"], "exclusions": ["Fuel", "Driver", "Helper"], "gst_percent": "12"}


def coorg_route():
    return {"name": "Coorg, stay in Virajpet", "distance_km_from_base": 245, "travel_hours_from_base": 6, "usual_nights": 2,
            "stops": [{"name": "Kushalnagar", "order": 1, "distance_km_from_previous": 215},
                      {"name": "Virajpet partner stay", "order": 2, "distance_km_from_previous": 30, "overnight": True},
                      {"name": "Jakkur office", "order": 3, "distance_km_from_previous": 240}],
            "sights": [{"name": "Abbey Falls", "km_round_trip": 80}, {"name": "Raja's Seat", "km_round_trip": 70}]}


def krs_route(km=160):
    return {"name": "KRS Backwaters", "distance_km_from_base": km, "travel_hours_from_base": 4, "usual_nights": 1,
            "stops": [{"name": "KRS site", "order": 1, "distance_km_from_previous": km, "overnight": True},
                      {"name": "Jakkur office", "order": 2, "distance_km_from_previous": km}],
            "sights": [{"name": "Brindavan Gardens", "km_round_trip": 6}]}


RESELLER = {"tiers": [{"name": "Travel agents", "commission_percent": "10", "min_commission_percent": "7.5", "max_commission_percent": "11.5",
                       "min_days": 2, "min_billing": "50000"}]}


def pub(db, w, kind, key, data):
    d = bds.create_draft(db, w.t.id, kind, key, data, w.owner.id)
    return bds.publish(db, w.t.id, d.id, w.owner.id)


def ratha(db):
    w = _workspace(db)
    for name in ("Ratha 1", "Ratha 2"):
        db.add(Property(id=str(uuid.uuid4()), tenant_id=w.t.id, name=name, slug=f"r-{uuid.uuid4().hex[:6]}", type="caravan", max_adults=8, max_children=0))
    db.commit()
    pub(db, w, "destination", "coorg", coorg_route())
    pub(db, w, "destination", "krs", krs_route())
    pub(db, w, "destination", "far", krs_route(km=350))
    pub(db, w, "package", "day-rate", day_rate())
    pub(db, w, "package", "coorg-48", coorg_48())
    pub(db, w, "package", "all-inclusive", all_inclusive())
    pub(db, w, "package", "travel-only", travel_only())
    pub(db, w, "reseller_terms", None, RESELLER)
    pub(db, w, "payment_policy", None, {"advance_percent": 50, "balance_due_days_before_checkin": 1, "confirmed_by_ratha": True})
    db.commit()
    return w


@pytest.fixture()
def r(db):
    return ratha(db)


def price(db, w, package_key, nights=2, adults=4, children=0, **kw):
    return pps.quote(db, w.t.id, package_key, START, START + timedelta(days=nights), adults, children, **kw)


def lines(q):
    return {l.label: l.amount for l in q.lines}


# ─── the plans ────────────────────────────────────────────────────────────────────────────────────────────

def test_coorg_48_hours_flat_price_with_extra_km_and_a_kit(r, db):
    q = price(db, r, "coorg-48", adults=5, children=1, destination_key="coorg", sights=["Raja's Seat"], extras=[{"name": "Culinary"}])
    assert q.ok, q.message
    assert lines(q) == {"Coorg 48-hour Retreat - 48 hours": Decimal("70000.00"), "Extra kilometres": Decimal("5250.00"), "Culinary": Decimal("5000.00")}
    assert q.km["planned_km"] == Decimal("555") and q.km["included_km"] == Decimal("480") and q.km["extra_km"] == Decimal("75")
    assert q.km["rate_mode"] == "fixed" and q.km["applied_rate"] == Decimal("70.00")
    assert q.subtotal == Decimal("80250.00") and q.gst == Decimal("9630") and q.total == Decimal("89880.00")
    assert q.advance_percent == Decimal("50.00") and q.advance == Decimal("44940")
    assert q.at_actuals == ["Tolls and parking"] and q.days == 2 and q.duration_hours == 48
    assert "48 hours" in q.lines[0].detail
    assert q.valid_until == TODAY + timedelta(days=3)


def test_coorg_48_extra_guest_is_once_per_trip_and_extra_hours_use_the_hour_rate(r, db):
    q = price(db, r, "coorg-48", adults=8, destination_key="coorg", extra_hours=3)
    assert q.ok and lines(q)["Extra guests"] == Decimal("5000.00")             # 2 above the 6 included x 2,500, once
    assert lines(q)["Extra hours"] == Decimal("6000.00")


def test_coorg_48_is_only_for_coorg_and_only_48_hours(r, db):
    wrong = price(db, r, "coorg-48", destination_key="krs")
    assert wrong.reason == "destination_not_in_package" and wrong.fix == {"destination_key": "coorg"} and wrong.total is None
    short = price(db, r, "coorg-48", nights=1, destination_key="coorg")
    assert short.reason == "below_min_nights" and short.fix == {"nights": 2}


def test_day_rate_two_days_six_guests(r, db):
    q = price(db, r, "day-rate", adults=6, destination_key="krs")
    assert q.ok, q.message
    assert lines(q) == {"Day rate - Day rate": Decimal("50000.00"), "Extra guests": Decimal("10000.00")}      # 2 x 2,500 x 2 days
    assert q.km["planned_km"] == Decimal("320") and q.km["included_km"] == Decimal("500") and q.km["extra_km"] == Decimal("0")
    assert q.subtotal == Decimal("60000.00") and q.gst == Decimal("7200") and q.total == Decimal("67200.00")
    assert q.at_actuals == ["Tolls and parking"]


def test_a_day_trip_with_no_nights_is_billed_one_day(r, db):
    q = price(db, r, "day-rate", nights=0, destination_key="krs")
    assert q.ok and q.days == 1 and lines(q)["Day rate - Day rate"] == Decimal("25000.00") and q.km["included_km"] == Decimal("250")


def test_extra_km_rate_is_the_agents_pick_within_the_range_and_is_stored(r, db):
    suggested = price(db, r, "day-rate", destination_key="far")              # 700 km, 500 included -> 200 extra
    assert suggested.km["extra_km"] == Decimal("200") and suggested.km["suggested_rate"] == Decimal("90.00")
    assert suggested.km["applied_rate"] == Decimal("90.00") and lines(suggested)["Extra kilometres"] == Decimal("18000.00")
    picked = price(db, r, "day-rate", destination_key="far", km_rate=Decimal("60"))
    assert picked.km["applied_rate"] == Decimal("60") and lines(picked)["Extra kilometres"] == Decimal("12000.00")
    assert picked.inputs["km_rate"] == "60" and picked.to_snapshot()["km"]["applied_rate"] == "60"
    too_high = price(db, r, "day-rate", destination_key="far", km_rate=Decimal("110"))
    assert too_high.reason == "km_rate_out_of_range" and too_high.fix == {"km_rate": "90.00"} and too_high.total is None
    fixed = price(db, r, "coorg-48", destination_key="coorg", sights=["Raja's Seat"], km_rate=Decimal("60"))
    assert fixed.reason == "km_rate_out_of_range"                             # a fixed 70 cannot be changed


def test_sights_add_their_round_trip_and_unknown_ones_are_refused(r, db):
    q = price(db, r, "day-rate", destination_key="krs", sights=["Brindavan Gardens"])
    assert q.km["planned_km"] == Decimal("326") and q.km["sights"] == [{"name": "Brindavan Gardens", "km": Decimal("6")}]
    assert price(db, r, "day-rate", destination_key="krs", sights=["Taj Mahal"]).reason == "unknown_sight"
    assert price(db, r, "day-rate", sights=["Brindavan Gardens"]).reason == "unknown_sight"


def test_a_route_with_a_missing_distance_cannot_be_counted(r, db):
    gap = krs_route()
    gap["stops"][1].pop("distance_km_from_previous")
    pub(db, r, "destination", "gap", gap)
    assert price(db, r, "day-rate", destination_key="gap").reason == "route_km_unknown"


def test_all_inclusive_needs_a_level_and_includes_the_kits(r, db):
    need = price(db, r, "all-inclusive")
    assert need.reason == "level_required" and need.fix["levels"] == ["35000", "40000", "45000"]
    assert price(db, r, "all-inclusive", level="50000").reason == "unknown_level"
    q = price(db, r, "all-inclusive", level="40000", destination_key="krs", extras=[{"name": "Culinary"}])
    assert q.ok and lines(q) == {"All-inclusive - Level 40k": Decimal("80000.00"), "Culinary": Decimal("0")}
    assert q.level == "40000" and q.lines[1].detail == "included in this package"


def test_travel_only_needs_three_days_and_never_charges_km(r, db):
    short = price(db, r, "travel-only", destination_key="far")
    assert short.reason == "below_min_days" and short.fix == {"nights": 3} and short.total is None
    q = price(db, r, "travel-only", nights=3, destination_key="far")
    assert q.ok and lines(q) == {"Travel only - Caravan only": Decimal("45000.00")} and q.km["included_km"] is None
    assert q.at_actuals == []


def test_no_hour_rate_means_a_late_return_cannot_be_quoted(r, db):
    q = price(db, r, "day-rate", destination_key="krs", extra_hours=2)
    assert q.reason == "no_hour_rate" and q.fix == {"extra_hours": 0} and q.total is None


# ─── reseller ─────────────────────────────────────────────────────────────────────────────────────────────

def test_reseller_commission_is_on_the_pre_tax_billing_and_net_is_shown(r, db):
    q = price(db, r, "day-rate", adults=6, destination_key="krs", channel="reseller")
    assert q.ok and q.commission == {"channel": "reseller", "tier": "Travel agents", "percent": "10.00", "amount": "6000",
                                     "on_amount": "60000.00", "net_to_business": "54000.00", "min_percent": "7.50", "max_percent": "11.50"}
    assert q.total == Decimal("67200.00")                                      # the guest-facing total does not change
    top = price(db, r, "day-rate", adults=6, destination_key="krs", channel="reseller", commission_percent=Decimal("11.5"))
    assert top.commission["amount"] == "6900" and top.commission["net_to_business"] == "53100.00"
    assert price(db, r, "day-rate", adults=6, destination_key="krs", channel="reseller", commission_percent=Decimal("12")).reason == "commission_out_of_range"
    assert any(ref["kind"] == "reseller_terms" for ref in q.record_refs)


def test_reseller_minimum_days_and_minimum_billing(r, db):
    one_day = price(db, r, "day-rate", nights=1, destination_key="krs", channel="reseller")
    assert one_day.reason == "reseller_min_days" and one_day.fix == {"nights": 2}
    under = price(db, r, "travel-only", nights=3, channel="reseller")       # 45,000 before tax
    assert under.reason == "reseller_min_billing" and under.total is None
    assert price(db, r, "day-rate", destination_key="krs", channel="reseller").ok          # exactly 50,000 is enough


def test_reseller_needs_published_terms_and_a_known_tier(db):
    w = _workspace(db)
    db.add(Property(id=str(uuid.uuid4()), tenant_id=w.t.id, name="Ratha 1", slug=f"r-{uuid.uuid4().hex[:6]}", type="caravan", max_adults=8))
    db.commit()
    pub(db, w, "package", "day-rate", day_rate())
    assert price(db, w, "day-rate", channel="reseller").reason == "no_reseller_terms"
    pub(db, w, "reseller_terms", None, RESELLER)
    assert price(db, w, "day-rate", channel="reseller", reseller_tier="Gold").reason == "unknown_reseller_tier"


# ─── drafts, fallback, issuing ────────────────────────────────────────────────────────────────────────────

def test_a_draft_route_can_be_previewed_but_not_issued(r, db):
    from app.models.guest import Guest
    from app.models.inquiry import Inquiry, InquirySource
    bds.create_draft(db, r.t.id, "destination", "chikmagalur", krs_route(km=250) | {"name": "Chikmagalur"}, r.mgr.id)
    db.commit()
    preview = price(db, r, "day-rate", destination_key="chikmagalur", allow_drafts=True)
    assert preview.ok and preview.uses_drafts and preview.destination["status"] == "draft"
    assert any("waiting for approval" in w for w in preview.warnings)
    assert {"kind": "destination", "key": "chikmagalur", "status": "draft"}.items() <= preview.record_refs[1].items()
    final = price(db, r, "day-rate", destination_key="chikmagalur")
    assert final.reason == "destination_not_published" and "waiting for approval" in final.message
    g = Guest(id=str(uuid.uuid4()), tenant_id=r.t.id, name="Kiran", phone="+919800001234")
    db.add(g)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=r.t.id, guest_id=g.id, source=InquirySource.WA_DIRECT)
    db.add(inq)
    db.commit()
    with pytest.raises(qs.QuoteError) as e:
        qs.issue_quote(db, r.t.id, inq.id, preview)
    assert e.value.code == "uses_drafts"


def test_primary_and_fallback_are_priced_separately_and_issued_as_linked_options(r, db):
    from app.models.guest import Guest
    from app.models.inquiry import Inquiry, InquirySource
    from app.models.inquiry_360 import InquiryQuote
    g = Guest(id=str(uuid.uuid4()), tenant_id=r.t.id, name="Divya", phone="+919800001235")
    db.add(g)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=r.t.id, guest_id=g.id, source=InquirySource.WA_DIRECT)
    db.add(inq)
    db.commit()
    primary = price(db, r, "coorg-48", adults=5, children=1, destination_key="coorg", sights=["Raja's Seat"], extras=[{"name": "Culinary"}])
    fallback = price(db, r, "day-rate", adults=6, destination_key="krs", nights=1)
    # fallback: 1 day 25,000 + 2 extra guests 5,000 + 70 km over the 250 included at the suggested 100 = 37,000, + 12 % GST
    assert primary.total == Decimal("89880.00") and fallback.total == Decimal("41440.00")
    rows = qs.issue_options(db, r.t.id, inq.id, primary, fallback, r.owner.id, meta={"stay_check": "confirmed"})
    db.commit()
    assert [x.option_rank for x in rows] == [1, 2] and rows[0].option_group_id == rows[0].id == rows[1].option_group_id
    assert rows[1].amount == Decimal("41440.00") and rows[0].snapshot["meta"] == {"stay_check": "confirmed"}
    again = qs.issue_options(db, r.t.id, inq.id, primary, fallback, r.owner.id, meta={"stay_check": "confirmed"})
    assert [x.id for x in again] == [x.id for x in rows]                       # idempotent
    without = qs.issue_options(db, r.t.id, inq.id, primary, None, r.owner.id, meta={"stay_check": "confirmed"})
    db.commit()
    db.refresh(rows[1])
    assert without[0].id == rows[0].id and rows[1].is_active is False and rows[1].status == "superseded"
    changed = qs.issue_options(db, r.t.id, inq.id, primary, None, r.owner.id, meta={"stay_check": "checking"})
    db.commit()
    assert changed[0].id != rows[0].id
    assert db.query(InquiryQuote).filter_by(inquiry_id=inq.id, is_active=True).count() == 1


def test_pricing_never_reads_another_tenants_records(r, db):
    other = _workspace(db)
    assert price(db, other, "day-rate").reason == "package_not_published"
    bds.create_draft(db, r.t.id, "destination", "secret", krs_route(), r.owner.id)
    db.commit()
    pub(db, other, "package", "day-rate", day_rate())
    assert price(db, other, "day-rate", destination_key="secret", allow_drafts=True).reason == "destination_not_published"


# ─── schema rules ─────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,data,needle", [
    ("package", day_rate(extra_km_charge={"per_km": "70", "max_per_km": "100", "min_per_km": "60"}), "either a fixed per_km"),
    ("package", day_rate(extra_km_charge={"max_per_km": "100", "min_per_km": "60", "ladder": [{"per_km": "120"}]}), "outside"),
    ("package", day_rate(extra_km_charge={"max_per_km": "60", "min_per_km": "100"}), "min_per_km is above"),
    ("package", day_rate(extra_guest_charge={"free_guests": 4, "per_guest": "2500", "per_guest_per_night": "2500"}), "exactly one"),
    ("package", day_rate(included_km=500), "not both"),
    ("package", day_rate(rates=[_rate("a", "1", level="x"), {**_rate("b", "2"), "valid_from": (TODAY + timedelta(days=500)).isoformat(),
                                                               "valid_to": (TODAY + timedelta(days=600)).isoformat()}]), "level"),
    ("reseller_terms", {"tiers": [{"name": "A", "commission_percent": "12", "min_commission_percent": "7.5", "max_commission_percent": "11.5"}]}, "within"),
    ("reseller_terms", {"tiers": [{"name": "A", "commission_percent": "10", "min_commission_percent": "7.5"}]}, "both"),
    ("destination", coorg_route() | {"sights": [{"name": "A", "km_round_trip": 1}, {"name": "a", "km_round_trip": 2}]}, "same name"),
])
def test_new_terms_refuse_contradictions(kind, data, needle):
    model, problems = validate_data(kind, data)
    assert model is None and needle in " ".join(problems), problems


def test_records_without_the_new_terms_are_stored_exactly_as_before():
    from tests.test_business_data import coorg, package
    for kind, data in (("package", package()), ("destination", coorg())):
        stored = canonical(validate_data(kind, data)[0])
        for new in ("day_count", "min_days", "duration_hours", "included_km_per_day", "extra_hour_charge", "kits_included", "at_actuals",
                    "sights", "usual_nights"):
            assert new not in stored
    stored = canonical(validate_data("package", package())[0])
    assert stored["extra_guest_charge"] == {"free_guests": 2, "per_guest_per_night": "1500.00"} and stored["extra_km_charge"] == {"per_km": "18.00"}
    assert "level" not in stored["rates"][0]
