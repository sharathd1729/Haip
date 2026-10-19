"""The owner dashboard, layout A (``owner`` in GET /dashboard/business-overview, 19 Oct 2026).

Pinned: the new KPI definitions (qualified = phone + check-in date; booked value = rental + add-ons), the monthly target on
booked value with its pace line (D-24), the check-in window parameter, organic calls as a first-touch source, leads by stage
with Lost by reason and spam apart (D-22: no phone, not counted), caravans per property, the six attention cards, and the
visibility rules (restricted blocks, amounts only with revenue.read, 403 for a role without analytics, nothing from another
workspace). The data is built around today (IST), so every block that reads "this month" or "from today" has something to show.
"""
import calendar
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.conversation import Conversation, Message
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource, InquiryStage, LostReason
from app.models.property import Property, Stay
from app.models.sales_target import SalesTarget
from app.models.stay_finance import StayAddOn, StayPayment
from app.models.user import UserRole
from app.services import owner_dashboard_attention, owner_dashboard_blocks
from app.services.date_presets import IST
from tests.api.test_business_overview import URL, _agent_scorecard, _stage, _tenant, _user  # noqa: F401 (autouse fixture: SQLite stand-in for the PG-only scorecard)

TODAY = datetime.now(IST).date()
NOW = datetime.now(timezone.utc)
EARLY_TODAY = datetime.combine(TODAY, datetime.min.time(), tzinfo=IST).astimezone(timezone.utc) + timedelta(minutes=30)


def _person(db, tid, name, *, phone=True, first_touch="whatsapp", when=EARLY_TODAY):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name=name, phone=f"+9197{uuid.uuid4().int % 10**8:08d}" if phone else "",
              lead_identified_at=when if phone else None, first_touch_channel=first_touch, first_touch_at=when)
    db.add(g); db.flush()
    return g


def _enquiry(db, tid, guest, stage, *, source=InquirySource.WA_DIRECT, when=EARLY_TODAY, **kw):
    i = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, stage=InquiryStage.NEW, stage_id=stage.id, source=source,
                created_at=when, **kw)
    db.add(i); db.flush()
    return i


def _booking(db, tid, prop, guest, *, amount, check_in_days, nights=2, created=EARLY_TODAY, inquiry=None):
    ci = TODAY + timedelta(days=check_in_days)
    s = Stay(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, property_id=prop.id, inquiry_id=inquiry.id if inquiry else None,
             check_in=ci, check_out=ci + timedelta(days=nights), status="confirmed", total_amount=amount, created_at=created)
    db.add(s); db.flush()
    return s


@pytest.fixture()
def shop(db):
    t = _tenant(db)
    tid = t.id
    owner, h_owner = _user(db, tid, UserRole.OWNER)
    agent, h_agent = _user(db, tid, UserRole.CONCIERGE, "Krisha")
    active = _stage(db, tid, "active", "Active", "valid", 1)
    lost = _stage(db, tid, "lost", "Lost", "valid", 2, lost=True)
    sold = _stage(db, tid, "sold", "Sold", "valid", 3, won=True)
    r1 = Property(id=str(uuid.uuid4()), tenant_id=tid, name="Ratha 1", slug=f"r1-{uuid.uuid4().hex[:4]}", type="caravan", is_active=True)
    r2 = Property(id=str(uuid.uuid4()), tenant_id=tid, name="Ratha 2", slug=f"r2-{uuid.uuid4().hex[:4]}", type="caravan", is_active=True)
    db.add_all([r1, r2]); db.flush()

    dated = _person(db, tid, "Dated")
    _enquiry(db, tid, dated, active, check_in=(TODAY + timedelta(days=9)).isoformat(), assigned_to=agent.id)
    undated = _person(db, tid, "Undated")
    _enquiry(db, tid, undated, lost, lost_reason=LostReason.BUDGET_MISMATCH)
    spam = _person(db, tid, "Spam")
    _enquiry(db, tid, spam, active, qualification_status="unqualified", check_in=(TODAY + timedelta(days=9)).isoformat())
    dm = _person(db, tid, "DM only", phone=False, first_touch="instagram")
    _enquiry(db, tid, dm, active)                                   # D-22: no phone, never counted
    organic = _person(db, tid, "Caller", first_touch="call")
    _enquiry(db, tid, organic, active, source=InquirySource.ORGANIC_CALL)
    untouched = _person(db, tid, "No touch", first_touch=None)
    _enquiry(db, tid, untouched, active, source=InquirySource.ORGANIC_CALL)
    buyer = _person(db, tid, "Buyer")
    won = _enquiry(db, tid, buyer, sold, assigned_to=agent.id)

    s1 = _booking(db, tid, r1, buyer, amount=25000, check_in_days=2, inquiry=won)
    db.add(StayAddOn(tenant_id=tid, stay_id=s1.id, name="Bonfire", quantity=2, unit_price=2500))
    db.add(StayPayment(tenant_id=tid, stay_id=s1.id, kind="payment", amount=10000, method="upi", paid_on=TODAY))
    s2 = _booking(db, tid, r2, buyer, amount=40000, check_in_days=10, nights=3)
    db.add(SalesTarget(tenant_id=tid, scope_type="tenant", scope_id=None, period_month=TODAY.replace(day=1), target_amount=600000))
    db.add(SalesTarget(tenant_id=tid, scope_type="agent", scope_id=agent.id, period_month=TODAY.replace(day=1), target_amount=100000))

    other = _tenant(db)
    o_stage = _stage(db, other.id, "active", "Active", "valid", 1)
    op = Property(id=str(uuid.uuid4()), tenant_id=other.id, name="Elsewhere", slug=f"o-{uuid.uuid4().hex[:4]}", type="villa", is_active=True)
    db.add(op); db.flush()
    og = _person(db, other.id, "Stranger")
    _enquiry(db, other.id, og, o_stage, check_in=(TODAY + timedelta(days=3)).isoformat())
    _booking(db, other.id, op, og, amount=987654, check_in_days=1)
    db.commit()
    return dict(t=t, tid=tid, h_owner=h_owner, h_agent=h_agent, agent=agent, r1=r1, r2=r2, s1=s1, s2=s2, other=other)


def _owner(client, headers, **params):
    r = client.get(URL, params={"date_preset": "this_month", **params}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["owner"]


def test_kpis_count_people_with_a_phone_and_split_booked_value(client, shop):
    k = _owner(client, shop["h_owner"])["kpis"]
    assert k["new_leads"]["count"] == 6                               # DM only has no phone (D-22)
    assert k["qualified"]["count"] == 1                               # only "Dated": phone + check-in date, spam excluded
    assert k["bookings"]["count"] == 2
    bv = k["booked_value"]
    assert (bv["rental"], bv["add_ons"], bv["total"]) == (65000, 5000, 70000)
    assert k["payment_received"]["amount"] == 10000
    assert k["bookings"]["change"] is None and bv["change"] is None   # nothing in the period before: no change, never -100%


def test_the_monthly_target_is_measured_on_booked_value_with_a_pace_line(client, shop):
    t = _owner(client, shop["h_owner"])["target"]
    days = calendar.monthrange(TODAY.year, TODAY.month)[1]
    assert t["available"] is True and t["target"] == 600000
    assert t["booked"] == {"total": 70000, "rental": 65000, "add_ons": 5000, "count": 2}
    assert t["pace_pct"] == round(TODAY.day / days * 100, 1)
    assert t["to_go"] == 530000 and t["days_left"] == days - TODAY.day
    assert t["expected_by_today"] == round(600000 * TODAY.day / days, 2)
    assert t["payment_received"] == 10000


def test_no_target_gives_an_empty_state_with_a_link(client, db, shop):
    db.query(SalesTarget).filter_by(tenant_id=shop["tid"]).delete()
    db.commit()
    t = _owner(client, shop["h_owner"])["target"]
    assert t["available"] is False and t["href"] == "/dashboard/targets" and t["booked"]["total"] == 70000


@pytest.mark.parametrize("window,expected", [(3, 1), (7, 1), (15, 2), (30, 2)])
def test_the_check_in_window_is_a_parameter(client, shop, window, expected):
    m = _owner(client, shop["h_owner"], window_days=window)["movements"]
    assert m["window_days"] == window and m["check_ins"] == expected
    first = m["items"][0]
    assert first["guest"] == "Buyer" and first["property"] == "Ratha 1" and first["kind"] == "check_in"


def test_when_leads_want_to_travel_counts_open_dated_leads_and_booked_stays_by_week(client, shop):
    tr = _owner(client, shop["h_owner"])["travel"]
    weeks = tr["weeks"]
    assert len(weeks) == owner_dashboard_blocks.TRAVEL_WEEKS + 1 and weeks[-1]["start"] is None
    week = lambda days: min(owner_dashboard_blocks.TRAVEL_WEEKS, (TODAY.weekday() + days) // 7)
    expected_active = [0] * len(weeks)
    expected_active[week(9)] += 1                                     # "Dated" only: spam and the other workspace are left out
    assert [w["active"] for w in weeks] == expected_active
    expected_booked = [0] * len(weeks)
    for days in (2, 10):
        expected_booked[week(days)] += 1
    assert [w["booked"] for w in weeks] == expected_booked


def test_a_window_other_than_3_7_15_30_is_refused(client, shop):
    assert owner_dashboard_attention.WINDOWS == (3, 7, 15, 30)
    r = client.get(URL, params={"date_preset": "this_month", "window_days": 5}, headers=shop["h_owner"])
    assert r.status_code == 422


def test_organic_calls_are_their_own_source_never_unknown(client, shop):
    j = client.get(URL, params={"date_preset": "this_month"}, headers=shop["h_owner"]).json()
    by = {s["key"]: s for s in j["sources"]}
    assert by["organic_call"]["leads"] == 2 and by["organic_call"]["label"] == "Organic calls"
    assert "unknown" not in by


def test_leads_by_stage_breaks_down_lost_and_keeps_spam_apart(client, shop):
    st = _owner(client, shop["h_owner"])["stages"]
    counts = {s["key"]: s["count"] for s in st["stages"]}
    assert counts == {"active": 3, "lost": 1, "sold": 1}             # Dated, Caller, No touch; the DM-only enquiry is not a lead's
    assert st["lost_by_reason"] == [{"reason": "budget_mismatch", "label": "Budget", "count": 1}]
    assert st["unqualified"] == 1


def test_caravans_show_value_nights_and_share_of_the_month(client, shop):
    c = _owner(client, shop["h_owner"])["caravans"]
    by = {i["name"]: i for i in c["items"]}
    assert by["Ratha 1"]["booked_value"] == 30000 and by["Ratha 2"]["booked_value"] == 40000
    days = c["days_in_month"]
    for name, check_in, nights in (("Ratha 1", 2, 2), ("Ratha 2", 10, 3)):
        start = TODAY + timedelta(days=check_in)
        in_month = max(0, min(nights, (TODAY.replace(day=days) - start).days + 1)) if start.month == TODAY.month else 0
        assert by[name]["nights"] == in_month
        assert by[name]["occupancy_pct"] == round(in_month / days * 100)


def test_the_six_attention_cards_and_owing_money(client, shop):
    cards = _owner(client, shop["h_owner"])["attention"]
    assert [c["key"] for c in cards] == ["not_replying", "not_called", "missed_calls", "followups", "at_risk", "owing"]
    owing = cards[-1]
    assert owing["count"] == 2 and owing["amount"] == 60000           # 30,000 - 10,000 paid, plus 40,000
    assert owing["people"][0]["name"] == "Buyer" and owing["href"] == "/dashboard/bookings?quick=due"
    not_called = next(c for c in cards if c["key"] == "not_called")
    assert not_called["count"] >= 1 and all(p["name"] != "DM only" for p in not_called["people"])


def test_team_shows_target_and_achieved_booked_value(client, shop):
    team = _owner(client, shop["h_owner"])["team"]
    row = next(r for r in team["rows"] if r["name"] == "Krisha")
    assert row["target"] == 100000 and row["achieved"] == 30000 and row["achieved_pct"] == 30.0
    assert row["leads_owned"] == 2


def test_an_agent_without_revenue_gets_no_amounts(client, shop):
    j = client.get(URL, params={"date_preset": "this_month"}, headers=shop["h_agent"]).json()
    owner = j["owner"]
    assert owner["kpis"]["booked_value"] == {"restricted": True} and owner["target"] == {"restricted": True}
    owing = next(c for c in owner["attention"] if c["key"] == "owing")
    assert owing["amount"] is None and all(p["amount"] is None for p in owing["people"])
    assert owner["team"] is None and owner["ai_calls"] is None
    assert "60000" not in json.dumps(owner) and "25000" not in json.dumps(owner)


def test_a_role_without_bookings_gets_restricted_blocks(client, db, shop):
    _, h = _user(db, shop["tid"], UserRole.MARKETING)               # analytics + revenue, no bookings.read
    owner = _owner(client, h)
    assert owner["movements"] == {"restricted": True} and owner["caravans"] == {"restricted": True}
    assert next(c for c in owner["attention"] if c["key"] == "owing") == {"key": "owing", "title": "Bookings still owing money",
                                                                          "restricted": True}


def test_compliance_is_refused_and_another_workspace_never_shows(client, db, shop):
    _, h = _user(db, shop["tid"], UserRole.COMPLIANCE)
    assert client.get(URL, params={"date_preset": "this_month"}, headers=h).status_code == 403
    text = json.dumps(_owner(client, shop["h_owner"], window_days=30))
    assert "987654" not in text and "Stranger" not in text and "Elsewhere" not in text
