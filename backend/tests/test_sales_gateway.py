"""The read-only gateway the AI uses for Ratha's structured data, and the facts the concierge prompt is built from.

  * only PUBLISHED records in effect today are ever returned (draft / rejected / scheduled / inactive are invisible);
  * missing, unconfirmed or contradictory data comes back as flags and no data -- never a plausible guess;
  * a published change is visible at once, with its version, and needs no knowledge re-index;
  * availability in a quote comes from the authoritative service;
  * the real prompt shows descriptive data always and money / payment terms only in the tenant's "grounded" price mode.
"""
import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.business_record import BusinessRecord
from app.models.property import BlockedDate, Property
from app.services import business_data_service as bds
from app.services import price_policy, sales_gateway as gw
from app.workers.tasks.concierge_draft import _check_grounding, _jinja_env
from tests.test_business_data import TODAY, _workspace, coorg, package
from tests.test_package_pricing import CI, CO, publish, rates, vehicle

ITIN = {"name": "Coorg in 3 days", "destination_key": "coorg", "nights": 2,
        "days": [{"day": 1, "title": "Drive to Madikeri", "stops": ["Madikeri"], "overnight_location": "Madikeri"},
                 {"day": 2, "title": "Estate walk"}, {"day": 3, "title": "Return"}], "package_keys": ["coorg-signature"]}


@pytest.fixture()
def ws(db):
    w = _workspace(db)
    vehicle(db, w)
    publish(db, w, "coorg", coorg(), kind="destination")
    publish(db, w, "coorg-signature", package(destination_keys=["coorg"], rates=[rates()]))
    publish(db, w, "coorg-3d", ITIN, kind="itinerary")
    return w


def policies(db, w, **over):
    publish(db, w, None, {"advance_percent": 30, "balance_due_days_before_checkin": 7, "confirmed_by_ratha": True}, kind="payment_policy")
    publish(db, w, None, {"tiers": [{"days_before": 15, "refund_percent": 100}, {"days_before": 7, "refund_percent": 50}], "confirmed_by_ratha": True}, kind="cancellation_policy")
    publish(db, w, None, {"max_discount_percent": 10, "requires_approval_above_percent": 5, "approver_roles": ["owner"]}, kind="discount_policy")
    publish(db, w, None, {"check_in_time": "14:00", "check_out_time": "11:00", "min_age": 5, "house_rules": ["No smoking inside"]}, kind="stay_rules")


# ─── published only ───────────────────────────────────────────────────────────────────────────────────────

def test_only_published_records_are_visible_and_each_answer_names_its_version(ws, db):
    r = gw.get_package(db, ws.t.id, "coorg-signature")
    assert r.ok and r.data["name"] == "Signature Caravan - Coorg" and r.sources[0] == {"kind": "package", "key": "coorg-signature", "version": 1, "effective_from": TODAY.isoformat()}
    assert r.flags == []
    assert [p["key"] for p in gw.list_packages(db, ws.t.id).data] == ["coorg-signature"]
    assert gw.get_destination(db, ws.t.id, "coorg").data["stops"][0]["name"] == "Madikeri"
    assert gw.get_itinerary(db, ws.t.id, "coorg-3d").data["days"][0]["overnight_location"] == "Madikeri"


def test_draft_rejected_scheduled_and_unknown_records_are_invisible(ws, db):
    draft = bds.create_draft(db, ws.t.id, "package", "secret", package(name="Secret", rates=[rates()]), ws.owner.id)
    bds.create_draft(db, ws.t.id, "package", "coorg-signature", package(name="Edited draft", rates=[rates("1")]), ws.owner.id)
    rej = bds.create_draft(db, ws.t.id, "destination", "goa", coorg() | {"name": "Goa"}, ws.owner.id)
    bds.reject(db, ws.t.id, rej.id, ws.owner.id, "no")
    sched = bds.create_draft(db, ws.t.id, "destination", "munnar", coorg() | {"name": "Munnar"}, ws.owner.id)
    bds.publish(db, ws.t.id, sched.id, ws.owner.id, effective_from=TODAY + timedelta(days=30))
    assert gw.get_package(db, ws.t.id, "secret").flags == ["not_published"] and gw.get_package(db, ws.t.id, "secret").data is None
    assert gw.get_package(db, ws.t.id, "coorg-signature").data["name"] == "Signature Caravan - Coorg"       # the draft edit is not served
    assert gw.get_destination(db, ws.t.id, "goa").data is None and gw.get_destination(db, ws.t.id, "munnar").data is None
    assert [d["key"] for d in gw.list_destinations(db, ws.t.id).data] == ["coorg"]
    assert draft.status == "draft"


def test_a_published_itinerary_change_is_retrieved_at_once_with_its_new_version(ws, db):
    assert gw.get_itinerary(db, ws.t.id, "coorg-3d").sources[0]["version"] == 1
    publish(db, ws, "coorg-3d", {**ITIN, "days": ITIN["days"][:2] + [{"day": 3, "title": "Sunset point, then return"}]}, kind="itinerary")
    r = gw.get_itinerary(db, ws.t.id, "coorg-3d")
    assert r.data["days"][2]["title"] == "Sunset point, then return" and r.sources[0]["version"] == 2
    assert [i["key"] for i in gw.get_itinerary(db, ws.t.id, package_key="coorg-signature").data] == ["coorg-3d"]


def test_filters_by_party_and_length_and_nothing_published_is_a_flag(ws, db):
    assert gw.list_packages(db, ws.t.id, guests=9).flags == ["no_package_matches"]
    assert gw.list_packages(db, ws.t.id, nights=1).data == []                       # min_nights is 2
    assert gw.list_packages(db, ws.t.id, guests=2, nights=2, destination_key="coorg").data
    empty = _workspace(db)
    assert gw.list_packages(db, empty.t.id).flags == ["none_published"] and gw.get_itinerary(db, empty.t.id).flags == ["not_published"]


def test_rates_are_withheld_unless_asked_for(ws, db):
    assert "rates" not in gw.get_package(db, ws.t.id, "coorg-signature", include_rates=False).data
    full = gw.get_package(db, ws.t.id, "coorg-signature").data
    assert full["rates"][0]["amount"] == "18000.00" and full["extra_km_charge"] == {"amount": "18.00"}


# ─── contradictions are flagged ──────────────────────────────────────────────────────────────────────────

def test_data_that_no_longer_agrees_is_flagged_not_hidden(ws, db):
    publish(db, ws, "coorg-3d", {**ITIN, "nights": 1, "days": ITIN["days"][:2]}, kind="itinerary")                      # package needs 2 nights
    assert "itinerary_nights_outside_package_range:coorg-signature" in gw.get_itinerary(db, ws.t.id, "coorg-3d").flags
    db.query(BusinessRecord).filter_by(tenant_id=ws.t.id, kind="destination", key="coorg").update({"status": "inactive"})
    db.commit()                                                                                                          # hand-edited row, bypassing the service
    assert "destination_not_published:coorg" in gw.get_package(db, ws.t.id, "coorg-signature").flags
    assert "destination_not_published:coorg" in gw.get_itinerary(db, ws.t.id, "coorg-3d").flags


# ─── quote ────────────────────────────────────────────────────────────────────────────────────────────────

def test_quote_package_prices_from_published_data_and_a_price_change_needs_no_reindex(ws, db):
    a = gw.quote_package(db, ws.t.id, "coorg-signature", CI, CO, 2)
    assert a.ok and a.data["total"] == "40320.00" and a.sources[0]["version"] == 1
    with patch("app.workers.tasks.embed_knowledge.embed_entry.delay", side_effect=AssertionError("no re-index")):
        publish(db, ws, "coorg-signature", package(destination_keys=["coorg"], rates=[rates("21000")]))
        b = gw.quote_package(db, ws.t.id, "coorg-signature", CI, CO, 2)
    assert b.data["total"] == "47040.00" and b.sources[0]["version"] == 2


def test_a_refused_quote_carries_a_reason_and_no_price(ws, db):
    r = gw.quote_package(db, ws.t.id, "coorg-signature", CI, CO, 9)
    assert not r.ok and r.flags == ["refused:over_capacity"] and "total" not in r.data and "lines" not in r.data
    db.add(BlockedDate(id=str(uuid.uuid4()), tenant_id=ws.t.id, property_id=db.query(Property).filter_by(tenant_id=ws.t.id).one().id,
                       blocked_from=CI.isoformat(), blocked_to=CO.isoformat(), reason="offline_booking"))
    db.commit()
    r = gw.quote_package(db, ws.t.id, "coorg-signature", CI, CO, 2)
    assert r.flags == ["refused:unavailable"] and r.data["availability"][0]["status"] == "unavailable"


# ─── policies ─────────────────────────────────────────────────────────────────────────────────────────────

def test_cancellation_discount_and_reseller_policies_are_applied_from_published_terms(ws, db):
    policies(db, ws)
    publish(db, ws, None, {"tiers": [{"name": "Agent A", "commission_percent": 10, "max_discount_percent": 5}]}, kind="reseller_terms")
    c = lambda d: gw.policy_check(db, ws.t.id, "cancellation", days_before_checkin=d)
    assert c(30).data["refund_percent"] == "100.00" and c(10).data["refund_percent"] == "50.00"
    assert c(2).data["refund_percent"] is None and c(2).flags == ["no_matching_tier"]                      # later than every tier: the team decides
    d = lambda p: gw.policy_check(db, ws.t.id, "discount", requested_percent=Decimal(p), base_amount=Decimal("36000")).data
    assert d(4)["status"] == "applied" and d(8)["status"] == "needs_approval" and d(15)["status"] == "refused"
    assert gw.policy_check(db, ws.t.id, "reseller", tier="agent a").data["commission_percent"] == "10.00"
    assert gw.policy_check(db, ws.t.id, "reseller", tier="nobody").flags == ["no_matching_tier"]
    assert gw.policy_check(db, ws.t.id, "stay_rules").data["check_in_time"] == "14:00"
    assert gw.policy_check(db, ws.t.id, "bogus").flags == ["unknown_policy:bogus"]


def test_a_policy_that_is_missing_or_unconfirmed_returns_no_data(ws, db):
    assert gw.policy_check(db, ws.t.id, "payment").flags == ["policy_not_published:payment_policy"]
    policies(db, ws)
    assert gw.policy_check(db, ws.t.id, "payment").data["advance_percent"] == "30.00"
    row = db.query(BusinessRecord).filter_by(tenant_id=ws.t.id, kind="payment_policy").one()
    row.data = {**row.data, "confirmed_by_ratha": False}                                                 # hand-edited row
    db.commit()
    r = gw.policy_check(db, ws.t.id, "payment")
    assert not r.ok and r.data is None and r.flags == ["policy_unconfirmed:payment_policy"]


def test_tenants_never_see_each_others_records(ws, db):
    other = _workspace(db)
    assert gw.get_package(db, other.t.id, "coorg-signature").data is None
    assert gw.list_packages(db, other.t.id).data == []
    assert gw.policy_check(db, other.t.id, "cancellation").data is None


# ─── facts for the concierge ──────────────────────────────────────────────────────────────────────────────

DETAILS = {"destination": "Coorg", "check_in": CI.isoformat(), "check_out": CO.isoformat(), "adults": 2}


def test_the_package_is_matched_only_when_the_guest_pointed_at_exactly_one(ws, db):
    assert gw.match_package(db, ws.t.id, DETAILS) == "coorg-signature"
    assert gw.match_package(db, ws.t.id, {"destination": "Wayanad"}) is None
    assert gw.match_package(db, ws.t.id, {}) is None
    publish(db, ws, "coorg-weekend", package(name="Coorg Weekend", destination_keys=["coorg"], rates=[rates()]))
    assert gw.match_package(db, ws.t.id, DETAILS) is None                                                  # two packages serve Coorg: ambiguous
    assert gw.match_package(db, ws.t.id, {"property_hint": "coorg weekend"}) == "coorg-weekend"


def test_concierge_facts_carry_descriptive_data_and_a_quote_with_sources(ws, db):
    policies(db, ws)
    facts = gw.concierge_business_facts(db, ws.t.id, DETAILS)
    by = {f["tool"]: f for f in facts}
    bd = by["business_data"]["result"]
    assert bd["packages"][0]["inclusions"] == ["Caravan with driver", "Bed linen"] and "rates" not in bd["packages"][0]
    assert bd["destinations"][0]["name"] == "Coorg" and bd["itineraries"][0]["name"] == "Coorg in 3 days" and bd["stay_rules"]["check_in_time"] == "14:00"
    assert by["package_quote"]["result"]["total"] == "40320.00" and by["package_quote"]["sources"][0]["version"] == 1
    assert {s["kind"] for s in by["business_data"]["sources"]} >= {"package", "destination", "itinerary", "stay_rules"}


def test_concierge_facts_are_empty_when_nothing_is_published_and_a_refusal_has_no_price(db):
    w = _workspace(db)
    assert gw.concierge_business_facts(db, w.t.id, DETAILS) == []
    vehicle(db, w)
    publish(db, w, "coorg", package(rates=[rates()]))
    facts = {f["tool"]: f for f in gw.concierge_business_facts(db, w.t.id, {**DETAILS, "adults": 9})}
    assert facts["package_quote"]["result"] == {"refused": "over_capacity", "message": facts["package_quote"]["result"]["message"]}
    assert "total" not in facts["package_quote"]["result"]


def _render(facts, mode):
    tenant = SimpleNamespace(brand_name="Ratha", brand_config={"price_disclosure": mode}, name="Ratha")
    prompt_facts = facts if mode == "grounded" else price_policy.redact_price_facts(facts)
    return _jinja_env.get_template("concierge_reply.jinja").render(
        tenant=tenant, guest=SimpleNamespace(name="G", language_pref="en", total_stays=0, predicted_csat=None, vip_tier=None, tags=[]), inquiry=None,
        recent_messages=[], call_summaries=[], kb_snippets=[], grounded_facts=prompt_facts, price_mode=mode, tone=None, guest_missing_phone=False,
        missing_details=[], qualified=False, property_info=[], guest_bookings=[])


def test_the_real_prompt_never_shows_a_price_in_handoff_mode(ws, db):
    policies(db, ws)
    out = _render(gw.concierge_business_facts(db, ws.t.id, DETAILS), "handoff")
    assert "PACKAGES, ROUTES AND POLICIES" in out and "Signature Caravan - Coorg" in out and "Madikeri" in out and "check-in 14:00" in out
    assert "40320" not in out and "36000" not in out and "18000" not in out and "advance" not in out.lower().split("pricing rule")[0].split("packages, routes and policies")[1]
    assert "Cancellation:" not in out and "Payment:" not in out
    assert price_policy.detect_price(out.split("PACKAGES, ROUTES AND POLICIES")[1].split("THIS GUEST")[0].split("LIVE AVAILABILITY")[0]) is None


def test_the_real_prompt_in_grounded_mode_shows_the_quote_and_confirmed_terms_only(ws, db):
    policies(db, ws)
    facts = gw.concierge_business_facts(db, ws.t.id, DETAILS)
    out = _render(facts, "grounded")
    assert "Package quote \"Signature Caravan - Coorg\"" in out and "total 40320.00 INR" in out and "advance 12096" in out
    assert "30.00% advance" in out and "100.00% refund if cancelled 15+ days" in out
    assert price_policy.unsupported_figures("The total comes to Rs 40,320 with an advance of Rs 12,096.", facts) == []
    assert price_policy.unsupported_figures("It is Rs 35,000.", facts) == [35000]
    refused = _render(gw.concierge_business_facts(db, ws.t.id, {**DETAILS, "adults": 9}), "grounded")
    assert "Package quote not possible (over capacity)" in refused and "40320" not in refused


def test_a_package_capacity_is_a_known_capacity_for_the_reply_guard(ws, db):
    facts = gw.concierge_business_facts(db, ws.t.id, {})
    assert _check_grounding("The Coorg package sleeps up to 4 guests.", facts)[0] is True
    assert _check_grounding("The Coorg package sleeps up to 7 guests.", facts)[0] is False
