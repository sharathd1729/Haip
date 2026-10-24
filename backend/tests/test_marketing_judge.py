"""Studio phase 5 (plan 24 Oct 2026): Conversions API lead events for click-to-WhatsApp chats, content ranked by what
it brought, opening tests decided with the analyst's half-and-half rule, autopilot per content type."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.models.ad_metrics import AdMetric
from app.models.consent import Consent
from app.models.lead_attribution import LeadAttribution
from app.models.marketing import InstagramPostMetricDaily, MarketingPublishAttempt
from app.models.marketing_ads import MarketingAdDraft, MarketingCapiEvent
from app.models.marketing_research import MarketingStrategyDoc
from app.services import marketing_ads_service as ads
from app.services import marketing_agency_service as agency
from app.services import marketing_capi as capi
from app.services import marketing_content_service as svc
from app.services import marketing_judge as judge
from tests.test_marketing_studio_content import BASE, seed_photos, ws  # noqa: F401  (fixture)
from tests.test_marketing_studio_insights import _chat, _lead

NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


class FakeWriter:
    def __init__(self):
        self.events = []

    def send_events(self, dataset_id, events, test_code=None):
        self.events += events
        return {"events_received": len(events), "fbtrace_id": "t"}

    def close(self):
        pass


def _ctwa(db, ws, *, consent=True, valid=True):  # noqa: F811
    tid = ws["tenant"].id
    g, inq = _lead(db, tid, valid=valid)
    g.lead_identified_at = NOW - timedelta(days=1)
    _chat(db, tid, g, inq, ad_id="AD1", at=NOW - timedelta(days=1))
    db.query(LeadAttribution).filter_by(inquiry_id=inq.id).update({"ctwa_clid": "CLID123"})
    if consent:
        db.add(Consent(tenant_id=tid, guest_id=g.id, scope="marketing", granted=True, channel="whatsapp",
                       recorded_at=NOW - timedelta(days=2)))
    db.commit()
    return g, inq


def _capi_on(db, ws, lead_events=True):  # noqa: F811
    ads.put_settings(db, ws["tenant"], {**ads.get_settings(ws["tenant"]), "capi_enabled": True, "dataset_id": "123456",
                                        "capi_lead_events": lead_events}, ws["owner"].id)
    db.commit()


def test_lead_events_are_sent_once_with_ctwa_clid_and_consent(db, ws):  # noqa: F811
    g, inq = _ctwa(db, ws)
    _capi_on(db, ws)
    w = FakeWriter()
    out = capi.send_tenant(db, ws["tenant"], writer_factory=lambda d, t: w, now=NOW)
    names = sorted(e["event_name"] for e in w.events)
    assert out["sent"] == 2 and names == ["LeadSubmitted", "QualifiedLead"]
    ev = w.events[0]
    assert ev["action_source"] == "business_messaging" and ev["messaging_channel"] == "whatsapp"
    assert ev["user_data"]["ctwa_clid"] == "CLID123" and "ph" in ev["user_data"] and g.phone not in str(ev)
    w2 = FakeWriter()
    capi.send_tenant(db, ws["tenant"], writer_factory=lambda d, t: w2, now=NOW)
    assert w2.events == []                                                   # never twice


def test_lead_events_are_off_by_default_and_need_consent(db, ws):  # noqa: F811
    _ctwa(db, ws, consent=False)
    _capi_on(db, ws, lead_events=False)
    w = FakeWriter()
    capi.send_tenant(db, ws["tenant"], writer_factory=lambda d, t: w, now=NOW)
    assert w.events == [] and db.query(MarketingCapiEvent).filter_by(tenant_id=ws["tenant"].id).count() == 0
    _capi_on(db, ws, lead_events=True)
    capi.send_tenant(db, ws["tenant"], writer_factory=lambda d, t: w, now=NOW)
    assert w.events == [] and {r.reason for r in db.query(MarketingCapiEvent)} == {"no marketing consent"}


def test_content_is_ranked_by_bookings_then_qualified_leads(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    a = svc.create_item(db, tid, kind="post", title="Ad post", actor_id=None, payload={"caption": "x"})
    b = svc.create_item(db, tid, kind="post", title="Quiet post", actor_id=None, payload={"caption": "x"})
    db.add(MarketingAdDraft(tenant_id=tid, content_id=a.id, version_id=a.current_version_id, content_sha="x" * 64,
                            destination="whatsapp", daily_budget_inr=500, days=7, spend_cap_inr=3500, audience={},
                            meta={"ad_id": "AD1"}))
    db.add(AdMetric(tenant_id=tid, ad_account_id="act", date=date(2026, 10, 20), ad_id="AD1", ad_name="AD1",
                    spend=Decimal(2000), impressions=4000, conversations_started=6))
    db.commit()
    _ctwa(db, ws)
    rank = judge.content_ranking(db, ws["tenant"], date(2026, 9, 27), date(2026, 10, 24))
    assert rank[0]["content_id"] == a.id and rank[0]["qualified"] == 1 and rank[0]["cost_per_qualified"] == 2000
    assert b.id not in {r["content_id"] for r in rank}


def test_opening_test_uses_the_half_and_half_rule(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    photo = seed_photos(db, tid, 1)[0]
    items = [svc.create_item(db, tid, kind="post", title=t, actor_id=None,
                             payload={"caption": "x", "media": {"asset_id": photo.id}}) for t in ("first", "trial")]
    for item, (x, n) in zip(items, ((40, 2000), (140, 2000))):
        db.add(MarketingPublishAttempt(tenant_id=tid, content_id=item.id, version_id=item.current_version_id, sha256="x" * 64,
                                       scheduled_for=NOW - timedelta(days=5), status="published", channel="instagram",
                                       media_ids=[f"m-{item.id}"], published_at=NOW - timedelta(days=5)))
        db.add(InstagramPostMetricDaily(tenant_id=tid, media_id=f"m-{item.id}", day="2026-10-23", reach=n,
                                        total_interactions=x))
    db.add(MarketingStrategyDoc(tenant_id=tid, kind="brief", title="b", status="ready",
                                input={"theme": "Diwali", "opening_tests": [{"a": items[0].id, "b": items[1].id,
                                                                             "a_hook": "One", "b_hook": "Two"}]}))
    db.commit()
    out = judge.opening_tests(db, tid, now=NOW)
    assert out[0]["status"] == "Second opening wins" and out[0]["b"]["rate"] > out[0]["a"]["rate"]


def test_autopilot_per_content_type_and_the_kill_switch(client, db, ws):  # noqa: F811
    t = ws["tenant"]
    r = client.put(f"{BASE}/agency", json={"roles": {"publish": "suggest"}, "publish_kinds": {"story": "autopilot"}},
                   headers=ws["owner_h"])
    assert r.status_code == 200 and r.json()["publish_kinds"] == {"story": "autopilot"}
    db.refresh(t)
    assert agency.publish_level(t, "story") == "autopilot" and agency.publish_level(t, "reel") == "suggest"
    assert client.put(f"{BASE}/agency", json={"publish_kinds": {"video": "autopilot"}}, headers=ws["owner_h"]).status_code == 422
    assert client.put(f"{BASE}/agency", json={"publish_kinds": {"reel": "autopilot"}}, headers=ws["manager_h"]).status_code == 403
    agency.update_agency(db, t, ws["owner"].id, paused=True)
    assert agency.publish_level(t, "story") == "suggest"                    # the kill switch wins
    agency.update_agency(db, t, ws["owner"].id, paused=False, roles={"publish": "off"})
    assert agency.publish_level(t, "story") == "off"                        # publishing off wins
