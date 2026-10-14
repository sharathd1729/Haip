"""GET /dashboard/business-overview -- the Owner Command Center.

What is pinned:
  * every figure matches a hand-computed value for a small, fully known workspace (leads, the lead -> booking -> payment
    cohort, bookings made, cash in / refunds, outstanding, per-source and per-agent splits, Meta Ads);
  * period edges are IST days; empty data gives zero counts and "no rate", never an error or a made-up percentage;
  * a viewer without bookings.read / revenue.read gets ``{"restricted": true}`` and the amounts are NOT in the payload
    at all; an agent only ever sees their own leads and the bookings linked to them, even if they ask for someone else;
  * another workspace's records never leak; filters (channel, property, agent) narrow every block consistently.

Runs on SQLite and PostgreSQL alike (the endpoint uses no PostgreSQL-only SQL). PostgreSQL has not been run for it.
"""
import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.ad_metrics import AdMetric
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.integration import Integration
from app.models.lead_attribution import LeadAttribution
from app.models.module import Module, WorkspaceModule
from app.models.pipeline_stage import PipelineStage
from app.models.property import Property, Stay
from app.models.sales_target import SalesTarget
from app.models.stay_finance import StayPayment
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import business_overview_extras as extras
from tests.conftest import seed_capabilities

D_FROM, D_TO = "2026-09-10", "2026-09-20"          # the reporting period used throughout (IST days)
URL = "/api/v1/dashboard/business-overview"


@pytest.fixture(autouse=True)
def _agent_scorecard(monkeypatch):
    """The per-agent scorecard (shared with the old dashboard) computes response times with PostgreSQL-only SQL
    (LATERAL, percentile_cont). On SQLite it is replaced by an empty scorecard; on PostgreSQL the real one runs."""
    if "sqlite" in os.environ.get("DATABASE_URL", "sqlite"):
        monkeypatch.setattr(extras, "get_agent_scorecard_rows", lambda *a, **k: [])


# ── a small, fully known workspace ──────────────────────────────────────────────────────────────────────────

def _ist(day: str, hh: int = 12, mm: int = 0) -> datetime:
    """An IST wall-clock time as the UTC instant that is stored."""
    d = datetime.fromisoformat(f"{day}T{hh:02d}:{mm:02d}:00+05:30")
    return d.astimezone(timezone.utc)


def _tenant(db, modules=("analytics",)):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"bo-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush()
    for code in modules:
        m = db.query(Module).filter_by(code=code).first() or Module(id=str(uuid.uuid4()), code=code, name=code)
        db.add(m); db.flush()
        db.add(WorkspaceModule(id=str(uuid.uuid4()), workspace_id=t.id, module_id=m.id, enabled=True))
    db.commit()
    seed_capabilities(db, t.id)
    return t


def _user(db, tid, role, name=None):
    u = User(id=str(uuid.uuid4()), tenant_id=tid, name=name or role.value, email=f"{role.value}-{uuid.uuid4().hex[:6]}@t.com",
             hashed_password=get_password_hash("pw"), role=role, is_active=True)
    db.add(u); db.commit()
    token = create_access_token({"sub": u.id, "tenant_id": tid, "role": role.value})
    return u, {"Authorization": f"Bearer {token}"}


def _stage(db, tid, key, label, category, order, won=False, lost=False):
    s = PipelineStage(id=str(uuid.uuid4()), tenant_id=tid, key=key, label=label, category=category, order=order,
                      is_closed_won=won, is_closed_lost=lost)
    db.add(s); db.flush()
    return s


def _lead(db, tid, stage, when, *, source=InquirySource.WA_DIRECT, assigned=None, prop=None, qualification="qualified"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="G", phone=f"+9197{uuid.uuid4().int % 10**8:08d}")
    db.add(g); db.flush()
    i = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, stage=InquiryStage.NEW, stage_id=stage.id, source=source,
                created_at=when, qualification_status=qualification, assigned_to=assigned, property_id=prop)
    db.add(i); db.flush()
    return i


def _stay(db, tid, prop, created, amount, *, lead=None, status="confirmed", check_in_days=30):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="G", phone=f"+9196{uuid.uuid4().int % 10**8:08d}")
    db.add(g); db.flush()
    ci = date.today() + timedelta(days=check_in_days)
    s = Stay(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, property_id=prop.id, inquiry_id=lead.id if lead else None,
             check_in=ci, check_out=ci + timedelta(days=2), status=status, total_amount=amount, created_at=created)
    db.add(s); db.flush()
    return s


def _pay(db, tid, stay, amount, day, kind="payment"):
    db.add(StayPayment(tenant_id=tid, stay_id=stay.id, kind=kind, amount=amount, method="upi", paid_on=date.fromisoformat(day)))
    db.flush()


@pytest.fixture()
def world(db):
    t = _tenant(db)
    tid = t.id
    owner, h_owner = _user(db, tid, UserRole.OWNER)
    manager, h_manager = _user(db, tid, UserRole.MANAGER)
    a1, h_a1 = _user(db, tid, UserRole.CONCIERGE, "Asha")
    a2, h_a2 = _user(db, tid, UserRole.RESERVATIONS, "Bala")

    s_new = _stage(db, tid, "general_enquiry", "General Enquiry", "invalid", 0)
    s_active = _stage(db, tid, "active", "Active", "valid", 1)
    s_sold = _stage(db, tid, "sold", "Sold", "valid", 2, won=True)
    pa = Property(id=str(uuid.uuid4()), tenant_id=tid, name="Villa A", slug=f"a-{uuid.uuid4().hex[:4]}", type="villa", is_active=True)
    pb = Property(id=str(uuid.uuid4()), tenant_id=tid, name="Villa B", slug=f"b-{uuid.uuid4().hex[:4]}", type="villa", is_active=True)
    db.add_all([pa, pb]); db.flush()

    l1 = _lead(db, tid, s_active, _ist("2026-09-12"), source=InquirySource.WA_DIRECT, assigned=a1.id, prop=pa.id)
    l2 = _lead(db, tid, s_sold, _ist("2026-09-13"), source=InquirySource.META_IG, assigned=a1.id, prop=pb.id)
    l3 = _lead(db, tid, s_new, _ist("2026-09-14"), source=InquirySource.PHONE, assigned=a2.id)
    l4 = _lead(db, tid, s_active, _ist("2026-09-15"), source=InquirySource.WEBSITE)
    l5 = _lead(db, tid, s_active, _ist("2026-09-16"), qualification="unqualified")        # spam: not a lead
    l6 = _lead(db, tid, s_active, _ist("2026-09-05"), assigned=a1.id)                     # before the period

    s1 = _stay(db, tid, pb, _ist("2026-09-13"), 50000, lead=l2)
    s2 = _stay(db, tid, pa, _ist("2026-09-14"), 30000, lead=l1)
    s3 = _stay(db, tid, pa, _ist("2026-09-15"), 10000)                                    # no lead link
    s4 = _stay(db, tid, pb, _ist("2026-09-16"), 20000, lead=l2, status="cancelled")
    s6 = _stay(db, tid, pa, _ist("2026-09-05"), 7000, lead=l6)                            # booked before the period
    _pay(db, tid, s1, 20000, "2026-09-13")
    _pay(db, tid, s1, 5000, "2026-09-15", kind="refund")
    _pay(db, tid, s3, 10000, "2026-09-16")

    # another workspace with data that must never appear
    other = _tenant(db)
    og = _stage(db, other.id, "active", "Active", "valid", 1)
    op = Property(id=str(uuid.uuid4()), tenant_id=other.id, name="Other", slug=f"o-{uuid.uuid4().hex[:4]}", type="villa", is_active=True)
    db.add(op); db.flush()
    ol = _lead(db, other.id, og, _ist("2026-09-12"))
    _stay(db, other.id, op, _ist("2026-09-12"), 999999, lead=ol)
    db.commit()
    return dict(tid=tid, tenant=t, h_owner=h_owner, h_manager=h_manager, h_a1=h_a1, h_a2=h_a2, a1=a1, a2=a2,
                pa=pa, pb=pb, leads=(l1, l2, l3, l4, l5, l6), stays=(s1, s2, s3, s4, s6), stages=(s_new, s_active, s_sold))


def _get(client, headers, **params):
    params = {"date_preset": "custom", "date_from": D_FROM, "date_to": D_TO, **params}
    return client.get(URL, params=params, headers=headers)


# ── the owner's numbers ──────────────────────────────────────────────────────────────────────────────────────

def test_the_leads_block_counts_what_the_catalogue_says(client, world):
    r = _get(client, world["h_owner"])
    assert r.status_code == 200, r.text
    leads = r.json()["leads"]
    assert leads["received"] == 4                    # l1..l4; spam and the earlier lead are out
    assert leads["valid"] == 3 and leads["invalid"] == 1
    assert leads["marked_spam_excluded"] == 1
    assert leads["converted_to_booking"] == 2        # l1 and l2 each have a counted booking; the cancelled one does not count
    assert leads["conversion_rate"] == 50.0
    assert "cohort" in leads["conversion_basis"]
    assert leads["unassigned_now"] >= 1              # l4 (and l5/l6 may count as open too); the work queue owns that rule


def test_the_funnel_is_a_cohort_with_a_rate_from_the_previous_stage(client, world):
    f = _get(client, world["h_owner"]).json()["funnel"]
    assert f["basis"] == "cohort"
    by = {s["key"]: s for s in f["stages"]}
    assert [by[k]["count"] for k in ("received", "valid", "booked", "paid")] == [4, 3, 2, 1]
    assert by["received"]["rate_from_previous"] is None
    assert by["valid"]["rate_from_previous"] == 75.0
    assert by["booked"]["rate_from_previous"] == 66.7
    assert by["paid"]["rate_from_previous"] == 50.0  # only l2 has net cash in (20,000 less a 5,000 refund)


def test_bookings_are_counted_by_the_day_they_were_made_and_unlinked_ones_are_disclosed(client, world):
    b = _get(client, world["h_owner"]).json()["bookings"]
    assert b["restricted"] is False
    assert b["confirmed_created"] == 3               # s1, s2, s3 (s6 predates the period, s4 is cancelled)
    assert b["cancelled_of_created"] == 1
    assert b["not_linked_to_a_lead"] == 1            # s3
    assert b["pending"]["available"] is False        # no such status exists in HAIP
    assert b["needs_payment"] == 3                   # s1 (35k owed), s2 (30k), s6 (7k): live and not fully paid
    assert b["payment_overdue"] == 0


def test_revenue_keeps_booked_value_cash_and_refunds_apart(client, world):
    r = _get(client, world["h_owner"]).json()["revenue"]
    assert r["restricted"] is False
    assert r["gross_booking_value"] == 90000.0       # 50,000 + 30,000 + 10,000, the stay charge
    assert r["collected"] == 30000.0                 # 20,000 + 10,000 by payment date
    assert r["refunds"] == 5000.0
    assert r["net_collected"] == 25000.0
    assert r["outstanding_on_live_bookings"] == 72000.0   # 35,000 + 30,000 + 7,000
    assert r["net_revenue"]["available"] is False    # no tax / commission data, so no such figure
    assert r["target"] == {"available": False, "reason": "No target is set for this month."}


def test_a_monthly_target_is_reported_when_one_is_set_and_the_period_is_one_month(client, db, world):
    db.add(SalesTarget(tenant_id=world["tid"], scope_type="tenant", scope_id=None, period_month=date(2026, 9, 1), target_amount=300000))
    db.commit()
    t = _get(client, world["h_owner"]).json()["revenue"]["target"]
    assert t["available"] is True and t["monthly_target"] == 300000.0
    spans = _get(client, world["h_owner"], date_from="2026-08-25", date_to="2026-09-05").json()["revenue"]["target"]
    assert spans["available"] is False and "one calendar month" in spans["reason"]


def test_sources_and_agents_attribute_only_linked_bookings(client, world):
    j = _get(client, world["h_owner"]).json()
    src = {s["key"]: s for s in j["sources"]}
    assert src["whatsapp"]["leads"] == 1 and src["whatsapp"]["bookings"] == 1 and src["whatsapp"]["booking_value"] == 30000.0
    assert src["instagram"]["leads"] == 1 and src["instagram"]["bookings"] == 1 and src["instagram"]["booking_value"] == 50000.0
    assert src["call"]["leads"] == 1 and src["call"]["bookings"] == 0
    assert src["website"]["leads"] == 1
    agents = {a["name"]: a for a in j["agents"]}
    assert agents["Asha"]["leads"] == 2 and agents["Asha"]["bookings"] == 2 and agents["Asha"]["booking_value"] == 80000.0
    assert agents["Bala"]["leads"] == 1 and agents["Bala"]["bookings"] == 0
    assert agents["Unassigned"]["leads"] == 1


def test_the_daily_series_covers_the_period_and_adds_up(client, world):
    s = _get(client, world["h_owner"]).json()["series"]
    assert s["days"][-1] == D_TO and D_FROM in s["days"]
    start = s["days"].index(D_FROM)
    assert s["period_start_index"] == start
    assert sum(s["leads"][start:]) == 4
    assert sum(s["bookings"][start:]) == 3
    assert sum(s["booking_value"][start:]) == 90000.0
    assert round(sum(s["net_collected"][start:]), 2) == 25000.0


def test_the_pipeline_lists_stages_for_the_same_leads(client, world):
    rows = {r["stage"]: r["count"] for r in _get(client, world["h_owner"]).json()["pipeline"]}
    assert rows == {"General Enquiry": 1, "Active": 2, "Sold": 1}


def test_previous_period_comparison_has_a_baseline_only_when_there_was_one(client, world):
    r = _get(client, world["h_owner"]).json()
    assert r["period"]["previous_from"] == "2026-08-30" and r["period"]["previous_to"] == "2026-09-09"
    # l6 (5 Sep) is the one lead in the previous period: 4 now against 1 before
    assert r["leads"]["received_change"] == {"pct": 300.0, "direction": "up"}
    assert r["funnel"]["stages"][0]["previous"] == 1
    # an earlier window with nothing before it has no baseline: no "+0%" and no "-100%"
    early = _get(client, world["h_owner"], date_from="2026-09-05", date_to="2026-09-06").json()
    assert early["leads"]["received"] == 1 and early["leads"]["received_change"] is None


# ── period edges, empty data, errors ─────────────────────────────────────────────────────────────────────────

def test_the_period_edge_is_the_ist_midnight(client, db, world):
    stage = world["stages"][1]
    _lead(db, world["tid"], stage, _ist("2026-10-01", 0, 0))                       # first minute of 1 Oct IST
    _lead(db, world["tid"], stage, _ist("2026-09-30", 23, 59))                     # last minute of 30 Sep IST
    db.commit()
    one_day = _get(client, world["h_owner"], date_from="2026-10-01", date_to="2026-10-01").json()
    assert one_day["leads"]["received"] == 1
    assert one_day["period"]["timezone"] == "Asia/Kolkata"


def test_an_empty_workspace_gives_zero_counts_and_no_rates(client, db):
    t = _tenant(db)
    _, h = _user(db, t.id, UserRole.OWNER)
    j = _get(client, h).json()
    assert j["leads"]["received"] == 0 and j["leads"]["conversion_rate"] is None
    assert all(s["count"] == 0 and s["rate_from_previous"] is None for s in j["funnel"]["stages"])
    assert j["bookings"]["confirmed_created"] == 0
    assert j["revenue"]["gross_booking_value"] == 0.0 and j["revenue"]["collected"] == 0.0
    assert j["sources"] == [] and j["pipeline"] == [] and j["meta_ads"] == {"configured": False}


@pytest.mark.parametrize("params,detail", [
    ({"channel": "carrier-pigeon"}, "Invalid channel"),
    ({"date_preset": "yesterdayish"}, "Invalid date_preset"),
    ({"date_from": "2026-09-20", "date_to": "2026-09-10"}, "must not be after"),
])
def test_bad_parameters_are_refused(client, world, params, detail):
    r = _get(client, world["h_owner"], **params)
    assert r.status_code == 422 and detail in r.json()["detail"]


def test_a_custom_range_needs_both_dates(client, world):
    r = client.get(URL, params={"date_preset": "custom"}, headers=world["h_owner"])
    assert r.status_code == 422


# ── who sees what ────────────────────────────────────────────────────────────────────────────────────────────

def test_an_agent_sees_only_their_own_leads_and_linked_bookings_and_no_money(client, world):
    r = _get(client, world["h_a1"])
    assert r.status_code == 200
    j = r.json()
    assert j["access"] == {"tenant_wide": False, "bookings": True, "revenue": False}
    assert j["leads"]["received"] == 2               # Asha's l1 and l2
    assert j["bookings"]["confirmed_created"] == 2   # their two linked bookings, not the workspace's three
    assert j["bookings"]["not_linked_to_a_lead"] is None
    assert j["revenue"] == {"restricted": True}
    assert j["agents"] is None and j["meta_ads"] is None and j["stale_integrations"] == []
    text = json.dumps(j)
    for amount in ("90000", "50000", "30000", "72000", "999999"):
        assert amount not in text, f"{amount} leaked to a viewer without revenue.read"


def test_an_agent_cannot_ask_for_someone_elses_numbers(client, world):
    j = _get(client, world["h_a2"], agent_id=world["a1"].id).json()
    assert j["leads"]["received"] == 1               # Bala's own lead, whatever agent_id says
    assert j["filters"]["agent_id"] is None


def test_the_owner_can_narrow_to_one_agent(client, world):
    j = _get(client, world["h_owner"], agent_id=world["a2"].id).json()
    assert j["leads"]["received"] == 1 and j["filters"]["agent_id"] == world["a2"].id
    assert j["agents"] is None                       # the all-agents table is for the unfiltered view
    assert j["bookings"]["not_linked_to_a_lead"] is None


def test_a_role_with_no_booking_rights_gets_a_restricted_bookings_block(client, db, world):
    _, h = _user(db, world["tid"], UserRole.MARKETING)     # analytics.read + revenue.read, no bookings.read
    j = _get(client, h).json()
    assert j["bookings"] == {"restricted": True}
    assert j["revenue"]["restricted"] is False


def test_compliance_is_refused_the_page_and_so_is_a_stranger(client, db, world):
    _, h = _user(db, world["tid"], UserRole.COMPLIANCE)
    assert _get(client, h).status_code == 403
    assert client.get(URL).status_code in (401, 403)


def test_the_page_needs_the_analytics_module(client, db):
    t = _tenant(db, modules=())
    _, h = _user(db, t.id, UserRole.OWNER)
    assert _get(client, h).status_code == 403


def test_a_manager_sees_the_whole_workspace_and_never_another(client, world):
    j = _get(client, world["h_manager"]).json()
    assert j["access"]["tenant_wide"] is True and j["leads"]["received"] == 4
    assert "999999" not in json.dumps(j)


# ── filters ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_channel_filter_narrows_leads_and_the_bookings_linked_to_them(client, world):
    j = _get(client, world["h_owner"], channel="instagram").json()
    assert j["leads"]["received"] == 1
    assert j["bookings"]["confirmed_created"] == 1 and j["revenue"]["gross_booking_value"] == 50000.0
    assert j["bookings"]["not_linked_to_a_lead"] is None       # unlinked bookings cannot be placed in a channel
    assert _get(client, world["h_owner"], channel="voice").json()["filters"]["channel"] == "call"


def test_the_property_filter_narrows_leads_bookings_and_cash(client, world):
    j = _get(client, world["h_owner"], property_id=world["pa"].id).json()
    assert j["leads"]["received"] == 1                           # l1 only: the other leads have another or no property
    assert j["bookings"]["confirmed_created"] == 2               # s2 and s3 are on Villa A
    assert j["revenue"]["gross_booking_value"] == 40000.0
    assert j["revenue"]["collected"] == 10000.0                  # s3's payment; s1's cash is on Villa B


# ── Meta Ads, integrations, freshness ────────────────────────────────────────────────────────────────────────

def test_meta_ads_separates_what_meta_reports_from_what_haip_verified(client, db, world):
    tid, l2 = world["tid"], world["leads"][1]
    db.add(Integration(id=str(uuid.uuid4()), tenant_id=tid, kind="meta_ads", status="active",
                       config={"ad_account_id": "act_1", "last_synced_at": "2026-09-20T01:00:00+00:00"}))
    db.add(AdMetric(tenant_id=tid, ad_account_id="act_1", date=date(2026, 9, 12), campaign_id="c1", ad_id="ad1",
                    spend=4000, conversations_started=10))
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=l2.guest_id, inquiry_id=l2.id, channel=ChannelType.INSTAGRAM)
    db.add(conv); db.flush()
    db.add(LeadAttribution(tenant_id=tid, inquiry_id=l2.id, conversation_id=conv.id, guest_id=l2.guest_id,
                           destination_channel="instagram", ad_id="ad1", first_message_at=_ist("2026-09-13"), created_at=_ist("2026-09-13")))
    db.commit()
    m = _get(client, world["h_owner"]).json()["meta_ads"]
    assert m["configured"] is True and m["spend"] == 4000.0
    assert m["reported_chats"] == 10 and m["verified_conversations"] == 1 and m["not_traced"] == 9
    assert m["verified_leads"] == 1 and m["verified_bookings"] == 1 and m["verified_booking_value"] == 50000.0
    assert m["cost_per_verified_lead"] == 4000.0 and m["return_on_spend"] == 12.5     # 50,000 booked from 4,000 spent


def test_a_stale_polled_integration_is_surfaced_for_the_owner(client, db, world):
    old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    db.add(Integration(id=str(uuid.uuid4()), tenant_id=world["tid"], kind="hostaway", status="active", last_health_at=old, config={}))
    db.commit()
    stale = _get(client, world["h_owner"]).json()["stale_integrations"]
    assert [s["kind"] for s in stale] == ["hostaway"] and stale[0]["status"] == "red"


def test_the_response_says_when_it_was_made(client, world):
    j = _get(client, world["h_owner"]).json()
    assert datetime.fromisoformat(j["generated_at"]).tzinfo is not None
    assert [a["key"] for a in j["attention"]][:4] == ["unassigned", "waiting_reply", "missed_calls", "followups"]


# ── the fuller owner view: lost leads, expected check-in, breakdowns, trend, Meta detail, agents, at-risk ──────

def test_lost_leads_and_expected_check_in_are_reported(client, db, world):
    tid, stages = world["tid"], world["stages"]
    lost = _stage(db, tid, "lost", "Lost", "valid", 9, lost=True)
    a = _lead(db, tid, lost, _ist("2026-09-17"))
    a.check_in = "2026-11-14"
    b = _lead(db, tid, stages[1], _ist("2026-09-18"))
    b.check_in = "2026-12-24"
    c = _lead(db, tid, stages[1], _ist("2026-09-18"))
    c.check_in = "not a date"
    db.commit()
    leads = _get(client, world["h_owner"]).json()["leads"]
    assert leads["lost"] == 1
    assert leads["by_expected_check_in"] == [{"month": "2026-11", "count": 1}, {"month": "2026-12", "count": 1}]
    assert leads["expected_check_in_unknown"] == 4 + 3 - 2     # 7 leads in the period, 2 with a usable date


def test_booking_breakdowns_by_property_and_channel_and_upcoming_checkouts(client, db, world):
    tid, pa, pb = world["tid"], world["pa"], world["pb"]
    s = _stay(db, tid, pa, _ist("2026-09-17"), 12000, check_in_days=-1)      # in house, leaves tomorrow
    s.channel_source = "airbnb"
    db.commit()
    b = _get(client, world["h_owner"]).json()["bookings"]
    assert b["upcoming_checkouts"] == 1
    prop = {r["name"]: r for r in b["by_property"]}
    assert prop["Villa A"]["bookings"] == 3 and prop["Villa A"]["value"] == 52000.0      # s2 30,000 + s3 10,000 + this 12,000
    assert prop["Villa B"]["bookings"] == 1 and prop["Villa B"]["value"] == 50000.0
    channel = {r["channel"]: r for r in b["by_channel"]}
    assert channel["airbnb"] == {"channel": "airbnb", "bookings": 1, "value": 12000.0}
    assert channel["direct"]["bookings"] == 3


def test_an_agent_gets_the_breakdowns_without_money(client, world):
    j = _get(client, world["h_a1"]).json()
    assert all(r["value"] is None for r in j["bookings"]["by_property"] + j["bookings"]["by_channel"])


@pytest.mark.parametrize("trend,expected_buckets", [("day", None), ("week", 12), ("month", 12)])
def test_the_trend_can_be_day_week_or_month(client, world, trend, expected_buckets):
    s = _get(client, world["h_owner"], trend=trend).json()["series"]
    assert s["granularity"] == trend
    if expected_buckets:
        assert len(s["days"]) == expected_buckets
    assert sum(s["leads"][s["period_start_index"]:]) >= 4
    assert sum(s["booking_value"]) >= 90000.0 and sum(s["bookings"]) >= 3
    if trend == "week":
        assert all(date.fromisoformat(d).weekday() == 0 for d in s["days"])           # buckets start on Monday
    if trend == "month":
        assert all(d.endswith("-01") for d in s["days"])


def test_a_bad_trend_is_refused_and_a_restricted_viewer_gets_no_money_series(client, world):
    assert _get(client, world["h_owner"], trend="decade").status_code == 422
    s = _get(client, world["h_a1"], trend="week").json()["series"]
    assert s["booking_value"] is None and s["net_collected"] is None and s["leads"] is not None


def test_meta_ads_reports_delivery_numbers_and_top_campaigns(client, db, world):
    tid, l2 = world["tid"], world["leads"][1]
    db.add(Integration(id=str(uuid.uuid4()), tenant_id=tid, kind="meta_ads", status="active", config={"ad_account_id": "act_1"}))
    for day, spend, imp, clk, chats, camp, name in [(date(2026, 9, 12), 3000, 20000, 400, 6, "c1", "Weekend Escape"),
                                                      (date(2026, 9, 13), 1000, 10000, 100, 2, "c2", "Monsoon Offer")]:
        db.add(AdMetric(tenant_id=tid, ad_account_id="act_1", date=day, campaign_id=camp, campaign_name=name, ad_id=f"ad-{camp}",
                        spend=spend, impressions=imp, clicks=clk, conversations_started=chats))
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=l2.guest_id, inquiry_id=l2.id, channel=ChannelType.INSTAGRAM)
    db.add(conv); db.flush()
    db.add(LeadAttribution(tenant_id=tid, inquiry_id=l2.id, conversation_id=conv.id, guest_id=l2.guest_id, destination_channel="instagram",
                           ad_id="ad-c1", first_message_at=_ist("2026-09-13"), created_at=_ist("2026-09-13")))
    db.commit()
    m = _get(client, world["h_owner"]).json()["meta_ads"]
    assert (m["impressions"], m["clicks"]) == (30000, 500)
    assert m["ctr"] == 1.67 and m["cpc"] == 8.0 and m["cpm"] == 133.33         # 4,000 spend
    top = m["campaigns"]
    assert [c["name"] for c in top] == ["Weekend Escape", "Monsoon Offer"]
    assert top[0]["spend"] == 3000.0 and top[0]["reported_chats"] == 6 and top[0]["verified_conversations"] == 1
    assert top[1]["verified_conversations"] == 0


def test_the_agent_table_merges_leads_bookings_messages_and_the_scorecard(client, db, world, monkeypatch):
    tid, a1 = world["tid"], world["a1"]
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=world["leads"][0].guest_id, inquiry_id=world["leads"][0].id,
                        channel=ChannelType.WHATSAPP)
    db.add(conv); db.flush()
    for i in range(3):
        db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction="outbound", channel="whatsapp",
                       body="hi", sender_id=a1.id, is_ai_generated=False, created_at=_ist("2026-09-14", 10 + i)))
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction="outbound", channel="whatsapp", body="note",
                   sender_id=a1.id, is_internal=True, created_at=_ist("2026-09-14", 13)))        # internal notes are not messages sent
    db.commit()
    monkeypatch.setattr(extras, "get_agent_scorecard_rows", lambda *a, **k: [{
        "agent_id": a1.id, "agent_name": "Asha", "leads_handled": 2, "avg_response_seconds": 540.0, "response_count": 7,
        "followups_total": 5, "followups_completed": 3, "followups_overdue": 1, "calls_answered": 9, "calls_missed": 4,
        "calls_missed_recovered": 1, "ai_drafts_total": 6, "ai_drafts_approved": 4, "ai_drafts_rejected": 1, "conversions": 1}])
    agents = {a["name"]: a for a in _get(client, world["h_owner"]).json()["agents"]}
    asha = agents["Asha"]
    assert (asha["leads"], asha["valid"], asha["invalid"]) == (2, 2, 0)
    assert (asha["bookings"], asha["booking_value"]) == (2, 80000.0)
    assert asha["messages_sent"] == 3
    assert (asha["calls_answered"], asha["calls_missed"], asha["callbacks_waiting"]) == (9, 4, 3)
    assert asha["avg_response_seconds"] == 540 and (asha["followups_completed"], asha["followups_overdue"]) == (3, 1)
    assert agents["Bala"]["invalid"] == 1 and agents["Bala"]["avg_response_seconds"] is None     # no scorecard data: unknown, not 0


def test_promising_leads_at_risk_come_from_the_work_queue_and_the_ai_reading(client, db, world):
    l4 = world["leads"][3]                                   # unassigned and open
    l4.ai_analysis = {"sentiment": "positive"}
    world["leads"][0].ai_analysis = {"sentiment": "neutral"}
    db.commit()
    j = _get(client, world["h_owner"]).json()
    risk = j["leads"]["high_intent_at_risk"]
    assert risk["count"] == 1 and risk["items"][0]["inquiry_id"] == l4.id and risk["items"][0]["reason"] == "nobody owns it"
    assert {"key": "high_intent_risk", "label": "Promising leads at risk", "count": 1, "oldest_at": None, "href": "/dashboard/leads"} in j["attention"]


# ── why a 403 happened must be readable: the page shows a different message for each cause ─────────────────

def test_a_missing_module_is_reported_as_such_and_a_missing_capability_is_not(client, db, world):
    t = _tenant(db, modules=())
    _, owner_h = _user(db, t.id, UserRole.OWNER)
    r = _get(client, owner_h)
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "module_not_enabled" and r.json()["detail"]["missing_modules"] == ["analytics"]

    _, compliance_h = _user(db, world["tid"], UserRole.COMPLIANCE)
    r = _get(client, compliance_h)
    assert r.status_code == 403 and isinstance(r.json()["detail"], str)                   # a role problem, not a workspace one


def test_a_workspace_with_no_capability_matrix_is_refused_not_opened(client, db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"bo-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.commit()
    m = db.query(Module).filter_by(code="analytics").first() or Module(id=str(uuid.uuid4()), code="analytics", name="analytics")
    db.add(m); db.flush()
    db.add(WorkspaceModule(id=str(uuid.uuid4()), workspace_id=t.id, module_id=m.id, enabled=True)); db.commit()
    _, h = _user(db, t.id, UserRole.OWNER)
    assert _get(client, h).status_code == 403                                             # fails closed: never an open door


@pytest.mark.parametrize("role", [UserRole.RESERVATIONS, UserRole.CONCIERGE, UserRole.FOH])
def test_operations_roles_get_their_own_numbers_and_no_workspace_wide_view(client, db, world, role):
    _, h = _user(db, world["tid"], role)
    r = _get(client, h)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["access"]["tenant_wide"] is False
    assert j["revenue"].get("restricted") is True and "999999" not in json.dumps(j)
