"""Steps 3-4: lessons reach the prompt; the sales agent's limits per area on Rathaa's PUBLISHED catalogue (the agent bench world):
discounts only through the price engine + the published policy (small booking, above the maximum, approval, peak dates, the
floor), routes only published and within the driving limit, b2b never quoted, and an experiment arm can never exceed them."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.analyst import AgentLesson, AnalystReport
from app.services import agent_bench, package_pricing_service as pps, sales_gateway
from app.services.learning import catalogue, lessons, limits, resolver


@pytest.fixture()
def bench(db):
    w = agent_bench.build_world(db)
    w.tenant.brand_config = {**(w.tenant.brand_config or {}), "learning": {"areas": {"prices": "act", "routes": "act"}}}
    db.commit()
    return w


def _scenario(sid):
    return next(s for s in agent_bench.load_scenarios() if s["id"] == sid)


def test_a_proven_lesson_reaches_the_reply_prompt_and_a_retired_one_does_not(db, bench):
    db.add(AgentLesson(tenant_id=bench.tenant.id, text="Asking for the WhatsApp number first: 60% gave it vs 20%.", metric="dm_to_lead",
                       sample=100, source_experiment_id="exp-1"))
    db.add(AgentLesson(tenant_id=bench.tenant.id, text="An old retired lesson.", metric="dm_to_lead", sample=50,
                       source_experiment_id="exp-0", status="retired"))
    db.add(AgentLesson(tenant_id=bench.tenant.id, text="Seen in 2 of the last 3 weekly briefs: x went down.", metric="dm_to_lead"))
    db.commit()
    out = agent_bench.run_scenario(db, bench, _scenario("instagram-faq"))
    assert "PROVEN FOR THIS BUSINESS" in out["prompt"] and "60% gave it vs 20%" in out["prompt"]
    assert "old retired lesson" not in out["prompt"] and "weekly briefs" not in out["prompt"]   # only experiment-proven ones


def test_repeated_significant_findings_become_a_lesson(db, bench):
    f = {"id": "f-dm_to_lead-down", "metric": "dm_to_lead", "label": "Contacts who gave a phone number", "direction": "down",
         "confidence": 0.99}
    rows = []
    for i in range(3):
        start = date(2026, 9, 7) + timedelta(weeks=i)
        r = AnalystReport(tenant_id=bench.tenant.id, kind="weekly_brief", period_start=start, period_end=start + timedelta(days=6),
                          facts={"findings": [f] if i != 1 else []}, brief={})
        db.add(r)
        rows.append(r)
    db.commit()
    made = lessons.from_findings(db, bench.tenant.id, rows[-1])
    assert len(made) == 1 and "2 of the last 3 weekly briefs" in made[0].text
    assert lessons.from_findings(db, bench.tenant.id, rows[-1]) == []                 # not twice


def test_without_the_learning_control_the_same_price_question_goes_to_a_person(db, bench):
    s = dict(_scenario("learning-listed-package-shows-price"))
    s["setup"] = {}
    out = agent_bench.run_scenario(db, bench, s)
    assert out["consult"] and not out["auto_sent"]                                  # the hook is what made the difference


# ── discounts ────────────────────────────────────────────────────────────────────────────────────────────────

def test_small_booking_never_gets_a_discount(db, bench):
    d = date.today() + timedelta(days=30)
    got = limits.discount_decision(db, bench.tenant, "mysuru-escape", d, d, 2, 0, 5)
    assert not got["allowed"] and got["code"].startswith("discount_")


def test_discount_above_the_policy_maximum_is_refused(db, bench):
    d = date.today() + timedelta(days=30)
    got = limits.discount_decision(db, bench.tenant, "grand-karnataka", d, d + timedelta(days=6), 4, 0, 15)
    assert not got["allowed"] and got["code"].startswith("discount_")


def test_a_policy_that_needs_approval_still_needs_it_when_prices_act(db, bench):
    d = date.today() + timedelta(days=30)
    got = limits.discount_decision(db, bench.tenant, "grand-karnataka", d, d + timedelta(days=6), 4, 0, 3)
    assert got["allowed"] is False and got["code"] == "discount_needs_approval"      # Rathaa: every discount needs an OK


def test_peak_dates_never_get_a_discount(db, bench):
    peak = agent_bench.peak_day(date.today())
    got = limits.discount_decision(db, bench.tenant, "grand-karnataka", peak - timedelta(days=3), peak + timedelta(days=3), 4, 0, 3)
    assert got == {**got, "allowed": False, "code": "peak_dates"}


def test_below_the_floor_is_refused_whatever_the_policy():
    pol = type("P", (), {"min_booking_amount": None, "max_discount_percent": Decimal("50"), "max_discount_amount": None,
                         "requires_approval_above_percent": Decimal("50")})()
    out = pps.evaluate_discount(pol, Decimal("20"), Decimal("100000"), floor_total=Decimal("90000"))
    assert out["status"] == "refused" and "lowest price" in out["reason"]


def test_discounts_need_a_person_unless_prices_act(db, bench):
    bench.tenant.brand_config = {**bench.tenant.brand_config, "learning": {"areas": {"prices": "suggest"}}}
    db.commit()
    d = date.today() + timedelta(days=30)
    assert limits.discount_decision(db, bench.tenant, "grand-karnataka", d, d + timedelta(days=6), 4, 0, 3)["code"] == "needs_person"


# ── routes ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_build_your_own_within_the_driving_limit_only(db, bench):
    from app.services import business_data_service as bds

    def hours(key):
        return float(bds.parse(bds.get_effective(db, bench.tenant.id, "destination", key)).travel_hours_from_base)
    far = max(catalogue.published(db, bench.tenant.id, "destination"), key=hours)
    assert hours(far) * 2 > 8                                                       # one day there and back is over 8 h
    d = date.today() + timedelta(days=40)
    one_day = limits.route_decision(db, bench.tenant, [far], d, d + timedelta(days=1))
    assert not one_day["allowed"] and one_day["code"] == "drive_limit"
    long = limits.route_decision(db, bench.tenant, [far], d, d + timedelta(days=9))
    assert long["allowed"], long
    assert limits.route_decision(db, bench.tenant, ["goa-beach"], d, d + timedelta(days=3))["code"] == "not_published"


def test_custom_routes_need_a_person_unless_routes_act(db, bench):
    bench.tenant.brand_config = {**bench.tenant.brand_config, "learning": {"areas": {"routes": "watch"}}}
    db.commit()
    d = date.today() + timedelta(days=40)
    assert limits.route_decision(db, bench.tenant, ["hampi"], d, d + timedelta(days=3))["code"] == "needs_person"


# ── b2b and experiment arms ──────────────────────────────────────────────────────────────────────────────────

def test_b2b_is_never_quoted_and_no_experiment_can_list_it(db, bench):
    d = date.today() + timedelta(days=30)
    res = sales_gateway.quote_package(db, bench.tenant.id, "rathaa-base-b2b", d, d + timedelta(days=2), 2)
    assert not res.ok and res.data["reason"] == "b2b_only"
    assert "rathaa-base-b2b" not in catalogue.published(db, bench.tenant.id, "package")
    with pytest.raises(catalogue.ChangeRefused):
        catalogue.validate(db, bench.tenant, "price_disclosure_per_package", {"packages": ["rathaa-base-b2b"]})
    with pytest.raises(catalogue.ChangeRefused):
        catalogue.validate(db, bench.tenant, "route_suggestion", {"ask": "goa", "route_key": "goa-beach"})


def test_an_arm_only_ever_tightens_or_shows_a_published_price(db, bench):
    eff = resolver.Effective(price_packages={"mysuru-escape"})
    assert resolver.price_mode_for_turn("handoff", eff, "rathaa-base-b2b", 15000) == "handoff"
    tight = catalogue.after_value(db, bench.tenant, "consult_threshold", {"above_inr": 200000})
    catalogue.write(db, bench.tenant, "consult_threshold", tight, None, actor="test")
    assert catalogue.after_value(db, bench.tenant, "consult_threshold", {"above_inr": 900000}) == 200000   # never loosens


def test_lesson_view_and_retire(db, bench):
    exp = type("E", (), {"tenant_id": bench.tenant.id, "id": "exp-9", "change_type": "playbook_wording", "title": "t"})()
    db.add(AgentLesson(tenant_id=bench.tenant.id, text="x", metric="dm_to_lead", change_type="playbook_wording",
                       source_experiment_id="exp-9", sample=1, created_at=datetime.now(timezone.utc)))
    db.commit()
    assert lessons.contradicted_by(db, exp) == 1
    assert lessons.view(db.query(AgentLesson).filter_by(tenant_id=bench.tenant.id).one())["status"] == "retired"
