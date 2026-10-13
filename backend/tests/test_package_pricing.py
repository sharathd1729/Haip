"""Package pricing from PUBLISHED records, issued-quote snapshots, and what happens when data is missing or contradictory.

The acceptance rules for the Ratha knowledge/configuration work:
  * a published price change reaches the next quote immediately, with no knowledge re-indexing;
  * drafts and rejected versions never influence a quote;
  * a quote already issued keeps its original amounts and record versions after any later change;
  * missing or conflicting data gives a typed refusal that carries no price;
  * availability comes from the authoritative service (bookings, blocks), not from the package record.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.audit_event import AuditEvent
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.inquiry_360 import InquiryQuote
from app.models.knowledge import KnowledgeEntry
from app.models.property import BlockedDate, Property, Stay
from app.services import business_data_service as bds
from app.services import package_pricing_service as pps
from app.services import quote_service as qs
from tests.test_business_data import TODAY, _tenant, _workspace, package, w  # noqa: F401  (w is a fixture)

CI = TODAY + timedelta(days=10)
CO = TODAY + timedelta(days=12)


def rates(amount="18000", frm=None, to=None, **kw):
    return {"label": "Standard", "valid_from": (frm or TODAY).isoformat(), "valid_to": (to or TODAY + timedelta(days=400)).isoformat(),
            "amount": amount, "unit": "night", **kw}


def publish(db, w, key, data, kind="package", **kw):
    d = bds.create_draft(db, w.t.id, kind, key, data, w.owner.id)
    return bds.publish(db, w.t.id, d.id, w.owner.id, **kw)


def vehicle(db, w, name="Caravan A", adults=4):
    p = Property(id=str(uuid.uuid4()), tenant_id=w.t.id, name=name, slug=f"v-{uuid.uuid4().hex[:6]}", type="caravan", max_adults=adults, max_children=0)
    db.add(p)
    db.commit()
    return p


@pytest.fixture()
def ws(db, w):
    vehicle(db, w)
    publish(db, w, "coorg", package(rates=[rates()]))
    return w


def q(db, w, **kw):
    args = dict(package_key="coorg", check_in=CI, check_out=CO, adults=2)
    args.update(kw)
    return pps.quote(db, w.t.id, args.pop("package_key"), args.pop("check_in"), args.pop("check_out"), args.pop("adults"), **args)


# ─── arithmetic ───────────────────────────────────────────────────────────────────────────────────────────

def test_a_plain_stay_is_priced_from_the_published_rate_with_gst_and_the_stated_conventions(ws, db):
    r = q(db, ws)
    assert r.ok and r.subtotal == Decimal("36000.00") and r.gst == Decimal("4320") and r.total == Decimal("40320.00")
    assert [(l.label, l.amount) for l in r.lines] == [("Signature Caravan - Coorg - Standard", Decimal("36000"))]
    assert "2 nights @ 18000.00" in r.lines[0].detail
    assert r.valid_until == TODAY + timedelta(days=3) and r.inclusions == ["Caravan with driver", "Bed linen"] and r.exclusions == ["Meals", "Toll"]
    assert r.advance is None and any("payment policy" in x for x in r.warnings)          # nothing invented: no 30 % default


def test_the_advance_comes_only_from_a_published_confirmed_payment_policy(ws, db):
    publish(db, ws, None, {"advance_percent": 30, "balance_due_days_before_checkin": 7, "confirmed_by_ratha": True}, kind="payment_policy")
    r = q(db, ws)
    assert r.advance_percent == Decimal("30.00") and r.advance == Decimal("12096") and r.warnings == []
    assert {"kind": "payment_policy", "key": "default"}.items() <= {k: v for k, v in r.record_refs[-1].items()}.items()


def test_extra_guests_extra_kilometres_and_chosen_experiences_are_added_from_typed_fields(ws, db):
    r = q(db, ws, adults=3, children=1, planned_km=Decimal("800"), extras=[{"name": "Bonfire"}])
    labels = {l.label: l.amount for l in r.lines}
    assert labels["Extra guests"] == Decimal("6000.00")              # (4 - 2 free) x 1500 x 2 nights
    assert labels["Extra kilometres"] == Decimal("3600.00")          # (800 - 600) x 18
    assert labels["Bonfire"] == Decimal("1500.00")
    assert r.subtotal == Decimal("47100.00")


def test_a_stay_that_crosses_two_seasons_is_priced_night_by_night(db, w):
    vehicle(db, w)
    publish(db, w, "coorg", package(rates=[rates("24000", frm=TODAY, to=CI), {**rates("18000", frm=CI + timedelta(days=1))}]))
    r = q(db, w)
    assert r.subtotal == Decimal("42000.00")
    assert len(r.lines) == 2


def test_weekend_rates_beat_the_everyday_rate_only_on_those_days(db, w):
    vehicle(db, w)
    publish(db, w, "coorg", package(rates=[rates("18000"), rates("26000", days_of_week=[4, 5])]))
    friday = CI + timedelta(days=(4 - CI.weekday()) % 7)
    assert q(db, w, check_in=friday, check_out=friday + timedelta(days=2)).subtotal == Decimal("52000.00")          # Fri + Sat nights
    sunday = friday + timedelta(days=2)
    assert q(db, w, check_in=sunday, check_out=sunday + timedelta(days=2)).subtotal == Decimal("36000.00")           # Sun + Mon nights


def test_a_package_price_is_chosen_by_the_check_in_date(db, w):
    vehicle(db, w)
    publish(db, w, "coorg", package(product="overnight", min_nights=0, rates=[{**rates("42000"), "unit": "package"}]))
    r = q(db, w, check_in=CI, check_out=CI + timedelta(days=1))
    assert r.ok and r.subtotal == Decimal("42000.00") and "package price" in r.lines[0].detail


# ─── discounts: the policy decides ───────────────────────────────────────────────────────────────────────

def test_discounts_follow_the_published_policy_and_never_the_callers_wish(ws, db):
    assert q(db, ws, discount_percent=Decimal("5")).reason == "no_discount_policy"
    publish(db, ws, None, {"max_discount_percent": 10, "requires_approval_above_percent": 5, "approver_roles": ["owner"]}, kind="discount_policy")
    applied = q(db, ws, discount_percent=Decimal("5"))
    assert applied.discount["status"] == "applied"
    assert applied.taxable == Decimal("34200.00") and applied.gst == Decimal("4104") and applied.total == Decimal("38304.00")
    approval = q(db, ws, discount_percent=Decimal("8"))
    assert approval.ok and approval.discount["status"] == "needs_approval" and approval.total == Decimal("40320.00")         # not applied
    refused = q(db, ws, discount_percent=Decimal("12"))
    assert refused.ok and refused.discount["status"] == "refused" and refused.total == Decimal("40320.00")
    assert applied.record_refs[-1]["kind"] == "discount_policy"


# ─── published vs draft, history ─────────────────────────────────────────────────────────────────────────

def test_a_published_price_change_reaches_the_next_quote_without_any_re_indexing(ws, db):
    db.add(KnowledgeEntry(id=str(uuid.uuid4()), tenant_id=ws.t.id, category="faq", question="Coorg?", content="Lovely.", source="manual",
                          review_status="approved", embedding_status="done"))
    db.commit()
    before = q(db, ws)
    with patch("app.services.knowledge_service.embed_entry", side_effect=AssertionError("re-index must not run")), \
         patch("app.workers.tasks.embed_knowledge.embed_entry.delay", side_effect=AssertionError("re-index must not be queued")):
        publish(db, ws, "coorg", package(rates=[rates("21000")]))
        after = q(db, ws)
    assert before.subtotal == Decimal("36000.00") and after.subtotal == Decimal("42000.00")
    assert db.query(KnowledgeEntry).filter_by(tenant_id=ws.t.id).one().embedding_status == "done"


def test_draft_and_rejected_versions_never_affect_a_quote(ws, db):
    draft = bds.create_draft(db, ws.t.id, "package", "coorg", package(rates=[rates("99999")]), ws.owner.id)
    assert q(db, ws).subtotal == Decimal("36000.00")
    bds.reject(db, ws.t.id, draft.id, ws.owner.id, "typo")
    assert q(db, ws).subtotal == Decimal("36000.00")
    scheduled = bds.create_draft(db, ws.t.id, "package", "coorg", package(rates=[rates("30000")]), ws.owner.id)
    bds.publish(db, ws.t.id, scheduled.id, ws.owner.id, effective_from=TODAY + timedelta(days=30))
    assert q(db, ws).subtotal == Decimal("36000.00")                                  # a scheduled change is not in force yet


def test_an_issued_quote_keeps_its_price_and_terms_after_a_later_change(ws, db):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=ws.t.id, name="Asha", phone="+919800000555")
    db.add(guest)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=ws.t.id, guest_id=guest.id, source=InquirySource.WA_DIRECT)
    db.add(inq)
    db.commit()
    issued = qs.issue_quote(db, ws.t.id, inq.id, q(db, ws), ws.owner.id)
    db.commit()
    assert issued.amount == Decimal("40320.00") and issued.status == "issued" and issued.record_refs[0]["version"] == 1
    assert qs.check_still_valid(db, ws.t.id, issued)["valid"] is True

    publish(db, ws, "coorg", package(rates=[rates("25000")]))
    db.refresh(issued)
    assert issued.amount == Decimal("40320.00") and issued.snapshot["subtotal"] == "36000.00"          # unchanged
    assert q(db, ws).subtotal == Decimal("50000.00")                                                    # new quotes use the new price
    verdict = qs.check_still_valid(db, ws.t.id, issued)
    assert verdict["valid"] is False and verdict["terms_changed"] == [{"kind": "package", "key": "coorg", "issued_version": 1, "current_version": 2}]
    assert qs.get_issued_quote(db, ws.t.id, issued.id).snapshot["lines"][0]["amount"] == "36000.00"


def test_issuing_is_idempotent_and_a_different_quote_supersedes_the_old_one(ws, db):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=ws.t.id, name="Asha", phone="+919800000556")
    db.add(guest)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=ws.t.id, guest_id=guest.id, source=InquirySource.WA_DIRECT)
    db.add(inq)
    db.commit()
    a = qs.issue_quote(db, ws.t.id, inq.id, q(db, ws), ws.owner.id)
    again = qs.issue_quote(db, ws.t.id, inq.id, q(db, ws), ws.owner.id)
    assert again.id == a.id and db.query(InquiryQuote).filter_by(inquiry_id=inq.id).count() == 1
    b = qs.issue_quote(db, ws.t.id, inq.id, q(db, ws, adults=3), ws.owner.id)
    db.refresh(a)
    assert b.id != a.id and a.status == "superseded" and a.is_active is False and b.is_active is True
    db.flush()
    assert db.query(AuditEvent).filter_by(tenant_id=ws.t.id, action="quote.issued").count() == 2


def test_a_refused_quote_cannot_be_issued_and_another_tenants_enquiry_is_not_found(ws, db):
    refused = q(db, ws, adults=9)
    with pytest.raises(qs.QuoteError) as e:
        qs.issue_quote(db, ws.t.id, "x", refused)
    assert e.value.code == "not_quotable"
    other = _tenant(db)
    og = Guest(id=str(uuid.uuid4()), tenant_id=other.id, name="Z", phone="+919800000557")
    db.add(og)
    db.flush()
    oi = Inquiry(id=str(uuid.uuid4()), tenant_id=other.id, guest_id=og.id, source=InquirySource.WA_DIRECT)
    db.add(oi)
    db.commit()
    with pytest.raises(qs.QuoteError) as e:
        qs.issue_quote(db, ws.t.id, oi.id, q(db, ws))
    assert e.value.status == 404


# ─── safe refusals: no price when data is missing or contradictory ───────────────────────────────────────

@pytest.mark.parametrize("kwargs,code", [
    ({"package_key": "nope"}, "package_not_published"),
    ({"adults": 5}, "over_capacity"),
    ({"adults": 2, "children": 3}, "over_capacity"),
    ({"check_out": CI + timedelta(days=1)}, "below_min_nights"),
    ({"check_in": TODAY - timedelta(days=2), "check_out": TODAY - timedelta(days=1)}, "dates_in_past"),
    ({"check_in": CO, "check_out": CI}, "invalid_dates"),
    ({"adults": 0}, "invalid_dates"),
    ({"extras": [{"name": "Helicopter"}]}, "unknown_extra"),
    ({"check_in": TODAY + timedelta(days=500), "check_out": TODAY + timedelta(days=502)}, "no_rate_for_dates"),
])
def test_missing_or_impossible_requests_are_refused_without_a_price(ws, db, kwargs, code):
    r = q(db, ws, **kwargs)
    assert r.status == "refused" and r.reason == code and r.total is None and r.subtotal is None and r.lines == [] and r.message


def test_conflicting_equally_specific_rates_are_refused_not_guessed(db, w):
    vehicle(db, w)
    publish(db, w, "coorg", package(rates=[rates("20000", days_of_week=[4]), rates("22000", days_of_week=[4, 5])]))
    friday = CI + timedelta(days=(4 - CI.weekday()) % 7)
    r = q(db, w, check_in=friday, check_out=friday + timedelta(days=2))
    assert r.reason == "conflicting_rates" and r.total is None


def test_kilometres_above_the_included_amount_with_no_published_rate_need_confirmation(db, w):
    vehicle(db, w)
    publish(db, w, "coorg", package(extra_km_charge=None, rates=[rates()]))
    r = q(db, w, planned_km=Decimal("900"))
    assert r.reason == "needs_confirmation" and r.total is None


def test_a_deactivated_or_never_published_package_cannot_be_quoted(ws, db):
    bds.deactivate(db, ws.t.id, "package", "coorg", ws.owner.id)
    assert q(db, ws).reason == "package_not_published"


# ─── availability is read from the authoritative service ─────────────────────────────────────────────────

def test_a_calendar_block_stops_the_quote_even_though_the_rate_exists(db, w):
    v = vehicle(db, w)
    publish(db, w, "coorg", package(rates=[rates()]))
    assert q(db, w).ok
    db.add(BlockedDate(id=str(uuid.uuid4()), tenant_id=w.t.id, property_id=v.id, blocked_from=CI.isoformat(), blocked_to=CO.isoformat(), reason="offline_booking"))
    db.commit()
    r = q(db, w)
    assert r.reason == "unavailable" and r.total is None and r.availability[0]["status"] == "unavailable"


def test_confirmed_bookings_block_and_cancelled_ones_do_not(db, w):
    v = vehicle(db, w)
    publish(db, w, "coorg", package(rates=[rates()]))
    g = Guest(id=str(uuid.uuid4()), tenant_id=w.t.id, name="Other", phone="+919800000601")
    db.add(g)
    db.flush()
    stay = Stay(id=str(uuid.uuid4()), tenant_id=w.t.id, guest_id=g.id, property_id=v.id, check_in=CI, check_out=CO, status="confirmed")
    db.add(stay)
    db.commit()
    assert q(db, w).reason == "unavailable"
    stay.status = "cancelled"
    db.commit()
    assert q(db, w).ok


def test_one_free_vehicle_is_enough_and_the_packages_vehicle_list_is_respected(db, w):
    a, b = vehicle(db, w, "A"), vehicle(db, w, "B")
    publish(db, w, "coorg", package(rates=[rates()], vehicle_property_ids=[a.id]))
    g = Guest(id=str(uuid.uuid4()), tenant_id=w.t.id, name="Other", phone="+919800000602")
    db.add(g)
    db.flush()
    db.add(Stay(id=str(uuid.uuid4()), tenant_id=w.t.id, guest_id=g.id, property_id=a.id, check_in=CI, check_out=CO, status="confirmed"))
    db.commit()
    assert q(db, w).reason == "unavailable"                      # B is free but is not part of this package
    publish(db, w, "coorg", package(rates=[rates()], vehicle_property_ids=[a.id, b.id]))
    r = q(db, w)
    assert r.ok and {v["property_name"]: v["status"] for v in r.availability} == {"A": "unavailable", "B": "available"}
    assert q(db, w, vehicle_property_id=a.id).reason == "unavailable"
    assert q(db, w, vehicle_property_id=str(uuid.uuid4())).reason == "vehicle_not_in_package"


def test_no_vehicle_at_all_is_unavailable_not_a_free_quote(db, w):
    publish(db, w, "coorg", package(rates=[rates()]))
    r = q(db, w)
    assert r.reason == "unavailable" and "no vehicle" in r.message


# ─── tenants ──────────────────────────────────────────────────────────────────────────────────────────────

def test_a_package_is_only_quotable_in_its_own_workspace(ws, db):
    other = _workspace(db)
    vehicle(db, other)
    assert pps.quote(db, other.t.id, "coorg", CI, CO, 2).reason == "package_not_published"
