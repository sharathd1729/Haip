"""Agency M5 (21 Oct 2026): boost rules (approved once), the Conversions API, funnel diagnosis and the monthly review."""
import hashlib
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.adapters.marketing.meta_ads import MetaAdsError
from app.models.ad_metrics import AdMetric
from app.models.base import gen_uuid
from app.models.consent import Consent
from app.models.conversation import ChannelType, Conversation
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.lead_attribution import LeadAttribution
from app.models.marketing_ads import MarketingAdDraft, MarketingCapiEvent
from app.models.property import Property, Stay
from app.models.user import UserRole
from app.services import marketing_ads_insights as insights
from app.services import marketing_ads_service as ads
from app.services import marketing_boost as boost
from app.services import marketing_capi as capi
from tests.test_marketing_ads import AUDIENCE, approved_post, ready
from tests.test_marketing_studio_content import make_user, ws  # noqa: F401  (fixture)

BASE = "/api/v1/marketing/studio/ads"
MONDAY = date(2026, 10, 19)
RULE = {"name": "Fill weekends", "condition": {"window": "weekend", "days_ahead": 10, "occupancy_below_pct": 50},
        "action": {"content": "latest_post", "daily_budget_inr": 1000, "days": 3, "max_total_inr": 2500}}


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr("app.services.marketing_agency_service.notify_needs_approval", lambda *a, **k: None)
    monkeypatch.setattr("app.services.media_storage.upload_marketing_media", lambda t, c, m, e: f"{t}/m/{uuid.uuid4().hex}")


def _vehicles(db, tid, n=2):
    for i in range(n):
        db.add(Property(tenant_id=tid, name=f"Ratha {i + 1}", slug=f"r{i}-{uuid.uuid4().hex[:6]}", type="caravan",
                        is_active=True))
    db.commit()


def _open(booked: set):
    """is_open patch: a (property name index, night) pair in `booked` is taken."""
    def fn(db_, tenant_id, prop_id, a, b):
        return a not in booked
    return fn


# ── Rules ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_rule_is_approved_once_and_an_edit_voids_it(client, db, ws):  # noqa: F811
    r = client.post(f"{BASE}/rules", json=RULE, headers=ws["mkt_h"])
    assert r.status_code == 201 and r.json()["status"] == "draft"
    rid = r.json()["id"]
    assert client.post(f"{BASE}/rules/{rid}/approve", headers=ws["manager_h"]).status_code == 403   # owner only
    r = client.post(f"{BASE}/rules/{rid}/approve", headers=ws["owner_h"])
    assert r.status_code == 200 and r.json()["in_force"] is True
    edited = {**RULE, "action": {**RULE["action"], "max_total_inr": 9000}}
    r = client.put(f"{BASE}/rules/{rid}", json=edited, headers=ws["mkt_h"])
    assert r.json()["status"] == "draft" and r.json()["in_force"] is False
    bad = {**RULE, "action": {**RULE["action"], "max_total_inr": 500}}               # under one day's budget
    assert client.post(f"{BASE}/rules", json=bad, headers=ws["mkt_h"]).status_code == 422
    _, foh_h = make_user(db, ws["tenant"].id, UserRole.FOH)
    assert client.post(f"{BASE}/rules", json=RULE, headers=foh_h).status_code == 403


def test_weekends_in_range_and_their_occupancy(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    got = boost.windows(db, ws["tenant"], RULE["condition"], MONDAY)
    assert [w["key"] for w in got] == ["weekend:2026-10-23"]                        # 30 Oct is 11 days out
    assert got[0]["nights"] == [date(2026, 10, 23), date(2026, 10, 24)]
    _vehicles(db, tid)
    with patch("app.services.calculator_service.calculator_service.is_open", side_effect=_open({"2026-10-23"})):
        assert boost.occupancy(db, tid, got[0]["nights"]) == 50.0                     # both vehicles taken Friday
    assert boost.latest_end_for("weekend:2026-10-23") == datetime(2026, 10, 23, 6, 30, tzinfo=timezone.utc)


def _approved_rule(db, ws, body=RULE):  # noqa: F811
    rule = boost.create_rule(db, ws["tenant"], body, ws["mkt"].id)
    boost.approve_rule(db, ws["tenant"], rule.id, ws["owner"].id)
    db.commit()
    return rule


def test_on_autopilot_an_empty_weekend_is_boosted_once_within_the_caps(db, ws):  # noqa: F811
    tenant = ws["tenant"]
    item = approved_post(db, ws)
    ready(db, ws, cap=10_000, level="autopilot")
    _vehicles(db, tenant.id)
    rule = _approved_rule(db, ws)
    queued = []
    with patch("app.services.calculator_service.calculator_service.is_open", side_effect=_open(set())):
        out = boost.evaluate(db, tenant, today=MONDAY, queue_push=lambda t, d: queued.append(d))
        again = boost.evaluate(db, tenant, today=MONDAY, queue_push=lambda t, d: queued.append(d))
    assert out[0]["action"] == "boosted", out
    assert out[0]["booked_pct"] == 0.0 and out[0]["content_id"] == item.id
    assert again[0]["action"] == "none" and len(queued) == 1                        # one boost per weekend, ever
    d = db.get(MarketingAdDraft, queued[0])
    assert (d.status, d.origin, d.rule_id, d.window_key, d.spend_cap_inr) == ("approved", "rule", rule.id,
                                                                               "weekend:2026-10-23", 2500)
    assert d.approved_by == ws["owner"].id and "approved once" in d.approval_note
    assert rule.last_result["action"] == "none" and rule.last_checked_at is not None   # the second check's result


def test_on_suggest_or_over_budget_the_boost_waits_for_a_person(db, ws):  # noqa: F811
    tenant = ws["tenant"]
    approved_post(db, ws)
    ready(db, ws, cap=1000, level="autopilot")                                     # cap 2,500 > budget 1,000
    _vehicles(db, tenant.id)
    _approved_rule(db, ws)
    queued = []
    with patch("app.services.calculator_service.calculator_service.is_open", side_effect=_open(set())):
        out = boost.evaluate(db, tenant, today=MONDAY, queue_push=lambda t, d: queued.append(d))
    assert out[0]["action"] == "waiting_for_approval" and "more than is left" in out[0]["reason"] and queued == []
    assert db.get(MarketingAdDraft, out[0]["draft_id"]).status == "draft"


def test_a_booked_weekend_or_an_unapproved_rule_does_nothing(db, ws):  # noqa: F811
    tenant = ws["tenant"]
    approved_post(db, ws)
    ready(db, ws, level="autopilot")
    _vehicles(db, tenant.id)
    rule = _approved_rule(db, ws)
    busy = {"2026-10-23", "2026-10-24"}
    with patch("app.services.calculator_service.calculator_service.is_open", side_effect=_open(busy)):
        assert boost.evaluate(db, tenant, today=MONDAY)[0]["action"] == "none"
    boost.update_rule(db, tenant, rule.id, RULE, ws["mkt"].id)
    db.commit()
    with patch("app.services.calculator_service.calculator_service.is_open", side_effect=_open(set())):
        assert boost.evaluate(db, tenant, today=MONDAY) == []
    assert db.query(MarketingAdDraft).filter_by(tenant_id=tenant.id).count() == 0


def test_check_is_a_dry_run(client, db, ws):  # noqa: F811
    tenant = ws["tenant"]
    approved_post(db, ws)
    ready(db, ws, level="autopilot")
    _vehicles(db, tenant.id)
    rule = _approved_rule(db, ws, {**RULE, "condition": {**RULE["condition"], "days_ahead": 60}})
    with patch("app.services.calculator_service.calculator_service.is_open", side_effect=_open(set())):
        r = client.post(f"{BASE}/rules/{rule.id}/check", headers=ws["mkt_h"])
    assert r.status_code == 200 and r.json()["action"] == "would_boost"
    assert db.query(MarketingAdDraft).filter_by(tenant_id=tenant.id).count() == 0


# ── Conversions API ─────────────────────────────────────────────────────────────────────────────────────────────────

class CapiWriter:
    def __init__(self, fail=None):
        self.sent, self.fail = [], fail

    def send_events(self, dataset_id, events, *, test_code=None):
        if self.fail:
            raise self.fail
        self.sent.append((dataset_id, json.loads(json.dumps(events)), test_code))
        return {"events_received": len(events), "fbtrace_id": "trace-1"}

    def close(self):
        pass


def _booking(db, tid, *, consent=True, amount=Decimal("18000"), clid=None, status="confirmed"):
    g = Guest(id=gen_uuid(), tenant_id=tid, name="Asha", phone="+919845012345", email="Asha@Example.com")
    db.add(g)
    prop = db.query(Property).filter_by(tenant_id=tid).first()
    if prop is None:
        prop = Property(tenant_id=tid, name="Ratha 1", slug=f"r-{uuid.uuid4().hex[:6]}", type="caravan", is_active=True)
        db.add(prop)
    db.flush()
    inq = Inquiry(id=gen_uuid(), tenant_id=tid, guest_id=g.id)
    db.add(inq)
    db.flush()
    if clid:
        conv = Conversation(id=gen_uuid(), tenant_id=tid, guest_id=g.id, inquiry_id=inq.id, channel=ChannelType.WHATSAPP,
                            is_open=True)
        db.add(conv)
        db.flush()
        db.add(LeadAttribution(tenant_id=tid, inquiry_id=inq.id, conversation_id=conv.id, guest_id=g.id,
                               destination_channel="whatsapp", ad_id="ad-1", ctwa_clid=clid,
                               first_message_at=datetime.now(timezone.utc)))
    if consent is not None:
        db.add(Consent(tenant_id=tid, guest_id=g.id, channel="whatsapp", scope="marketing", granted=consent,
                       recorded_at=datetime.now(timezone.utc).isoformat()))
    s = Stay(id=gen_uuid(), tenant_id=tid, guest_id=g.id, property_id=prop.id, inquiry_id=inq.id,
             check_in=date.today() + timedelta(days=9), check_out=date.today() + timedelta(days=10), status=status,
             total_amount=amount)
    db.add(s)
    db.commit()
    return s


def _capi_on(db, ws):  # noqa: F811
    ads.put_settings(db, ws["tenant"], {"capi_enabled": True, "dataset_id": "1234567890", "audience": AUDIENCE},
                     ws["owner"].id)
    db.commit()


def test_only_consented_bookings_are_sent_and_only_hashed(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    yes = _booking(db, tid, clid="clid-abc")
    no = _booking(db, tid, consent=None)
    gone = _booking(db, tid, status="cancelled")
    writer = CapiWriter()
    assert capi.send_tenant(db, ws["tenant"], writer_factory=lambda d, t: writer) == {"sent": 0, "skipped": "off"}
    _capi_on(db, ws)
    out = capi.send_tenant(db, ws["tenant"], writer_factory=lambda d, t: writer)
    assert out["sent"] == 1
    dataset, events, test_code = writer.sent[0]
    assert dataset == "1234567890" and test_code is None and len(events) == 1
    ev = events[0]
    assert ev["event_id"] == f"stay:{yes.id}" and ev["custom_data"] == {"value": 18000.0, "currency": "INR", "num_items": 1}
    assert ev["action_source"] == "business_messaging" and ev["user_data"]["ctwa_clid"] == "clid-abc"
    assert ev["user_data"]["ph"] == [hashlib.sha256(b"919845012345").hexdigest()]
    assert ev["user_data"]["em"] == [hashlib.sha256(b"asha@example.com").hexdigest()]
    raw = json.dumps(events)
    assert "9845012345" not in raw and "example.com" not in raw                      # nothing in clear text
    rows = {r.stay_id: r for r in db.query(MarketingCapiEvent).filter_by(tenant_id=tid)}
    assert rows[yes.id].status == "sent" and rows[no.id].reason == "no marketing consent"
    assert rows[gone.id].status == "skipped"
    assert capi.send_tenant(db, ws["tenant"], writer_factory=lambda d, t: writer) == {"sent": 0}   # never twice


def test_a_withdrawn_consent_before_sending_holds_the_event_back(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    s = _booking(db, tid)
    _capi_on(db, ws)
    capi.queue_new(db, ws["tenant"])
    db.add(Consent(tenant_id=tid, guest_id=s.guest_id, channel="whatsapp", scope="marketing", granted=False,
                   recorded_at=(datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()))
    db.commit()
    writer = CapiWriter()
    capi.send_tenant(db, ws["tenant"], writer_factory=lambda d, t: writer)
    assert writer.sent == [] and db.query(MarketingCapiEvent).filter_by(stay_id=s.id).one().status == "skipped"


def test_a_meta_error_is_retried_a_few_times(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    s = _booking(db, tid)
    _capi_on(db, ws)
    capi.send_tenant(db, ws["tenant"], writer_factory=lambda d, t: CapiWriter(fail=MetaAdsError("down", status=503)))
    row = db.query(MarketingCapiEvent).filter_by(stay_id=s.id).one()
    assert (row.status, row.tries) == ("failed", 1)
    writer = CapiWriter()
    capi.send_tenant(db, ws["tenant"], writer_factory=lambda d, t: writer)
    assert row.status == "sent" and row.tries == 2 and len(writer.sent) == 1


def test_capi_status_is_owner_only(client, db, ws):  # noqa: F811
    assert client.get(f"{BASE}/capi", headers=ws["manager_h"]).status_code == 403
    assert client.get(f"{BASE}/capi", headers=ws["owner_h"]).json()["enabled"] is False


# ── Insights + monthly review ───────────────────────────────────────────────────────────────────────────────────────

def _row(**kw):
    base = {"spend": 1000.0, "impressions": 10_000, "clicks": 200, "link_clicks": 200, "video_views": 3000,
            "conversations": 40, "days": 7, "bookings": 4}
    return {**base, **kw}


def test_the_first_weak_stage_is_the_one_to_fix():
    rows = {"good": _row(), "good2": _row(), "flat_hook": _row(video_views=500), "no_clicks": _row(link_clicks=40, clicks=40),
            "no_bookings": _row(bookings=0), "tiny": _row(impressions=300)}
    diag, medians = insights.diagnose(rows)
    assert diag["good"]["stage"] is None and medians["click"] == 0.02
    assert diag["flat_hook"]["stage"] == "hook" and "3 seconds" in diag["flat_hook"]["advice"]
    assert diag["no_clicks"]["stage"] == "click"
    assert diag["no_bookings"]["stage"] == "booking" and "reply speed" in diag["no_bookings"]["advice"]
    assert diag["tiny"]["stage"] is None and "Not enough signal" in diag["tiny"]["advice"]


def test_fatigue_needs_both_a_ctr_drop_and_a_high_frequency(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    today = date(2026, 10, 21)
    for i in range(12):
        day = today - timedelta(days=11 - i)
        late = i >= 9
        for ad, freq in (("tired", 3.2), ("fine", 1.4)):
            db.add(AdMetric(tenant_id=tid, ad_account_id="act_1", date=day, ad_id=ad, ad_name=ad, impressions=1000,
                            link_clicks=8 if late else 20, frequency=Decimal(str(freq)), spend=Decimal("300")))
    db.commit()
    got = insights.fatigue(db, tid, today)
    assert set(got) == {"tired"} and got["tired"]["ctr_last_3_days"] < got["tired"]["ctr_first_week"]


def test_monthly_review_keeps_kills_and_counts_cost_per_booking(client, db, ws):  # noqa: F811
    tid = ws["tenant"].id
    month = date(2026, 9, 1)
    for ad, spend in (("winner", 4000), ("winner2", 5000), ("loser", 12000), ("new", 300)):
        db.add(AdMetric(tenant_id=tid, ad_account_id="act_1", date=date(2026, 9, 10), ad_id=ad, ad_name=ad,
                        impressions=20_000, link_clicks=300, conversations_started=30, spend=Decimal(spend)))
    db.commit()
    with patch.object(insights, "bookings_by_ad", return_value={
            "winner": {"leads": 6, "bookings": 2, "revenue": 40_000.0},
            "winner2": {"leads": 5, "bookings": 1, "revenue": 18_000.0}, "loser": {"leads": 9, "bookings": 0, "revenue": 0.0}}):
        out = insights.monthly_review(db, ws["tenant"], month)
    verdicts = {a["ad_id"]: a["verdict"] for a in out["ads"]}
    assert verdicts == {"winner": "keep", "winner2": "keep", "loser": "kill", "new": "test_more"}
    assert out["totals"]["bookings"] == 3 and out["totals"]["cost_per_booking"] == round(21300 / 3, 2)
    assert next(a for a in out["ads"] if a["ad_id"] == "winner")["cost_per_booking"] == 2000.0
    assert client.get(f"{BASE}/review?month=2026-09", headers=ws["mkt_h"]).status_code == 403   # revenue: approvers only
    assert client.get(f"{BASE}/review?month=2026-09", headers=ws["manager_h"]).status_code == 200
    assert client.get(f"{BASE}/insights", headers=ws["owner_h"]).status_code == 200
