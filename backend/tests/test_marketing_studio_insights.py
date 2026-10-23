"""Studio phase 1 (plan 24 Oct 2026): ad watch curve, Reel metrics, creative tags, money funnel + organic tracking codes,
and the weekly Insights report (confidence rules, fatigue, number grounding)."""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.adapters.marketing.meta_ads import parse_row
from app.models.ad_metrics import AdMetric
from app.models.audit_event import AuditEvent
from app.models.base import gen_uuid
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.lead_attribution import LeadAttribution
from app.models.marketing import InstagramPostMetricDaily, MarketingCreativeTag
from app.models.pipeline_stage import PipelineStage
from app.models.property import Property, Stay
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import marketing_ads_insights as ads_insights
from app.services import marketing_ai_service as ai
from app.services import marketing_attribution as attribution
from app.services import marketing_content_service as svc
from app.services import marketing_insights as insights
from app.services import marketing_insights_report as report
from app.services import marketing_insights_stats as st
from app.services import marketing_links as links
from app.services import marketing_tagging as tagging
from tests.conftest import seed_capabilities
from tests.test_marketing_studio_content import BASE, enable_module, make_user, ws  # noqa: F401  (fixture)

TODAY = date(2026, 10, 21)               # Wednesday; last full week = 12-18 Oct


# ── Pure rules ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_shrinkage_pulls_small_samples_to_the_own_median():
    small = st.shrink(3, 10, prior_rate=0.05, prior_n=1000)          # 30% on 10 trials is mostly noise
    big = st.shrink(300, 1000, prior_rate=0.05, prior_n=1000)
    assert 0.05 < small["rate"] < 0.06 and big["rate"] > 0.15
    assert small["low"] <= small["rate"] <= small["high"]


def test_confidence_words_need_items_weeks_and_a_clear_range():
    clear = {"rate": 0.12, "low": 0.10, "high": 0.14}
    assert st.confidence(5, 2, clear, 0.05) == st.STRONG
    assert st.confidence(5, 1, clear, 0.05) == st.EARLY                 # no winner from one week
    assert st.confidence(2, 3, clear, 0.05) == st.NOT_ENOUGH            # fewer than 3 items
    assert st.confidence(4, 2, {"rate": 0.051, "low": 0.04, "high": 0.06}, 0.05) == st.NOT_ENOUGH


def test_group_elements_judges_only_groups_of_three_or_more():
    rows = [{"tags": {"hook_type": "question"}, "week": f"W{i % 2}", "num": 120, "den": 1000} for i in range(6)]
    rows += [{"tags": {"hook_type": "statement"}, "week": "W1", "num": 40, "den": 1000} for _ in range(9)]
    rows += [{"tags": {"hook_type": "pov"}, "week": "W1", "num": 500, "den": 1000} for _ in range(2)]
    out = st.group_elements(rows, {"hook_type": "Hook"}, num="num", den="den")
    vals = {v["value"]: v for v in out["fields"]["hook_type"]["values"]}
    assert vals["question"]["confidence"] == st.STRONG and vals["question"]["lift"] > 1
    assert vals["pov"]["judged"] is False and vals["pov"]["confidence"] == st.NOT_ENOUGH


def test_fatigue_needs_two_consecutive_weeks_of_all_three_signals():
    base = {"freq": 1.5, "ctr": 0.02, "cost_per_chat": 100}
    tired = {"freq": 3.4, "ctr": 0.012, "cost_per_chat": 150}
    worse = {"freq": 3.8, "ctr": 0.010, "cost_per_chat": 190}
    assert st.fatigued([base, tired, worse])
    assert not st.fatigued([base, base, worse])                          # one week only
    assert not st.fatigued([base, {**tired, "freq": 2.0}, worse])        # frequency under 3 in one week
    assert not st.fatigued([base, worse])


def test_shrunk_cost_does_not_crown_a_tiny_ad():
    tiny = st.shrunk_cost(500, 1, account_cost=1000)
    big = st.shrunk_cost(20000, 30, account_cost=1000)
    assert big < tiny


def test_parse_row_reads_the_watch_curve():
    v = lambda n: [{"action_type": "video_view", "value": str(n)}]   # noqa: E731
    row = parse_row({"ad_id": "A1", "date_start": "2026-10-12", "impressions": "4000", "inline_link_click_ctr": "1.25",
                     "actions": [{"action_type": "video_view", "value": "900"}],
                     "video_thruplay_watched_actions": v(300), "video_p25_watched_actions": v(700),
                     "video_p100_watched_actions": v(90), "video_avg_time_watched_actions": v("4.2")})
    assert row["video_views"] == 900 and row["video_thruplays"] == 300 and row["video_p25"] == 700
    assert row["video_p100"] == 90 and row["video_p50"] == 0 and row["video_avg_watch_s"] == Decimal("4.2")
    assert row["link_ctr"] == Decimal("1.25")


def test_poller_keeps_reel_watch_numbers(db, ws):  # noqa: F811
    from app.workers.tasks.instagram_insights_poll import InstagramPostSnapshot, _record_daily
    post = InstagramPostSnapshot(tenant_id=ws["tenant"].id, media_id="R1", media_type="VIDEO", reach=900)
    db.add(post)
    db.flush()
    _record_daily(db, ws["tenant"].id, post, {"media_product_type": "REELS", "views": 2500, "avg_watch_ms": 6400,
                                              "skip_rate": 41.5})
    row = db.query(InstagramPostMetricDaily).filter_by(tenant_id=ws["tenant"].id, media_id="R1").one()
    assert (row.views, row.avg_watch_ms, row.skip_rate, row.media_product_type) == (2500, 6400, 41.5, "REELS")


# ── Tags ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _snapshot(db, tid, media_id, caption="POV: you wake up at Kabini. DM us.", media_type="VIDEO", product="REELS"):
    from app.workers.tasks.instagram_insights_poll import InstagramPostSnapshot
    db.add(InstagramPostSnapshot(tenant_id=tid, media_id=media_id, media_type=media_type, caption=caption, reach=1000,
                                 posted_at="2026-10-14T05:00:00+0000"))
    db.add(InstagramPostMetricDaily(tenant_id=tid, media_id=media_id, day="2026-10-20", media_type=media_type,
                                    media_product_type=product, posted_at="2026-10-14T05:00:00+0000", reach=1000,
                                    total_interactions=80))
    db.commit()


def _fake_tags(task, tenant_id, system, user, tool):
    assert task == "marketing_tagging" and "Kabini" in user
    return ({"format": "photo", "hook_type": "pov", "destination": "Kabini ", "persona": "couple", "cta": "dm"},
            {"model": "m"}, "nvidia")


def test_tagging_reads_the_caption_and_keeps_the_platform_format(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    _snapshot(db, tid, "R1")
    ids = tagging.queue_untagged(db, tid)
    assert len(ids) == 1 and tagging.queue_untagged(db, tid) == []          # one record per subject
    with patch.object(ai, "_call", side_effect=_fake_tags):
        row = tagging.run_tag(db, tid, ids[0])
    assert row.status == "ready" and row.tags["format"] == "reel"          # the platform's type, not the AI's guess
    assert row.tags["destination"] == "kabini" and row.tags["hook_type"] == "pov" and row.prompt_version == "marketing-tagging-v1"


def test_owner_correction_is_final_audited_and_tenant_scoped(client, db, ws):  # noqa: F811
    tid = ws["tenant"].id
    _snapshot(db, tid, "R2")
    row_id = tagging.queue_untagged(db, tid)[0]
    db.commit()
    assert client.patch(f"{BASE}/tags/{row_id}", json={"persona": "family"}, headers=ws["mkt_h"]).status_code == 403
    r = client.patch(f"{BASE}/tags/{row_id}", json={"persona": "aliens"}, headers=ws["manager_h"])
    assert r.status_code == 422
    r = client.patch(f"{BASE}/tags/{row_id}", json={"persona": "family"}, headers=ws["manager_h"])
    assert r.status_code == 200 and r.json()["source"] == "owner" and r.json()["tags"]["persona"] == "family"
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="marketing.tags.corrected").count() == 1
    with patch.object(ai, "_call", side_effect=AssertionError("must not re-tag")):
        assert tagging.run_tag(db, tid, row_id).tags["persona"] == "family"
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    seed_capabilities(db, other.id)
    enable_module(db, other.id)
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    assert client.patch(f"{BASE}/tags/{row_id}", json={"persona": "solo"}, headers=other_h).status_code == 404
    assert client.get(f"{BASE}/tags", headers=other_h).json() == []


# ── Money funnel + organic tracking ─────────────────────────────────────────────────────────────────────────────────

def _lead(db, tid, *, phone=True, valid=True, at=None):
    stage = db.query(PipelineStage).filter_by(tenant_id=tid, key="active").first()
    if stage is None:
        stage = PipelineStage(tenant_id=tid, key="active", label="Active", category="valid")
        db.add(stage)
        db.flush()
    g = Guest(id=gen_uuid(), tenant_id=tid, name="Asha", phone=f"+9198450{uuid.uuid4().int % 10**5:05d}",
              lead_identified_at=datetime.now(timezone.utc) if phone else None)
    db.add(g)
    db.flush()
    inq = Inquiry(id=gen_uuid(), tenant_id=tid, guest_id=g.id, stage_id=stage.id if valid else None)
    if at:
        inq.created_at = at
    db.add(inq)
    db.commit()
    return g, inq


def _chat(db, tid, g, inq, *, ad_id=None, ref=None, first_text=None, at=None):
    conv = Conversation(id=gen_uuid(), tenant_id=tid, guest_id=g.id, inquiry_id=inq.id, channel=ChannelType.WHATSAPP,
                        is_open=True)
    db.add(conv)
    db.flush()
    if ad_id or ref:
        a = LeadAttribution(tenant_id=tid, inquiry_id=inq.id, conversation_id=conv.id, guest_id=g.id,
                            destination_channel="whatsapp", source_type="ad" if ad_id else "post", ad_id=ad_id,
                            raw_referral={"ref": ref} if ref else None, first_message_at=at or datetime.now(timezone.utc))
        if at:
            a.created_at = at
        db.add(a)
    if first_text:
        db.add(Message(tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.INBOUND,
                       channel=ChannelType.WHATSAPP, body=first_text))
    db.commit()


def _stay(db, tid, inq, amount=30000):
    prop = db.query(Property).filter_by(tenant_id=tid).first() or Property(
        tenant_id=tid, name="Ratha 1", slug=f"r-{uuid.uuid4().hex[:6]}", type="caravan", is_active=True)
    db.add(prop)
    db.flush()
    db.add(Stay(id=gen_uuid(), tenant_id=tid, guest_id=inq.guest_id, property_id=prop.id, inquiry_id=inq.id,
                check_in=TODAY + timedelta(days=20), check_out=TODAY + timedelta(days=22), status="confirmed",
                total_amount=Decimal(amount)))
    db.commit()


def test_ad_funnel_counts_people_with_a_phone_and_qualified_enquiries(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    at = datetime(2026, 10, 14, 6, tzinfo=timezone.utc)
    for phone, valid in ((True, True), (True, False), (False, True)):
        g, inq = _lead(db, tid, phone=phone, valid=valid)
        _chat(db, tid, g, inq, ad_id="AD1", at=at)
    out = ads_insights.bookings_by_ad(db, tid, date(2026, 10, 12), date(2026, 10, 18))["AD1"]
    assert out["leads"] == 3 and out["people"] == 2 and out["qualified"] == 2


def test_tracking_links_and_codes_credit_organic_posts(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    item = svc.create_item(db, tid, kind="post", title="Kabini", actor_id=None, payload={"caption": "x"})
    db.commit()
    code = links.campaign_for_content(item.id)
    t = links.tracking(db, ws["tenant"], item.id)
    assert t["code"] == code and t["instagram_dm"] is None              # no Instagram connected: no DM link
    g1, inq1 = _lead(db, tid)
    _chat(db, tid, g1, inq1, ref=code)                                   # ig.me/...?ref=<code>
    g2, inq2 = _lead(db, tid)
    _chat(db, tid, g2, inq2, first_text=f"Hi! I saw your post ({code})")  # wa.me prefilled text
    ts = attribution.touches(db, tid, [inq1, inq2])
    assert attribution.chain(ts[inq1.id])["credited"]["content_id"] == item.id
    assert attribution.chain(ts[inq2.id])["credited"]["content_id"] == item.id


def test_tracking_endpoint_is_tenant_scoped(client, db, ws):  # noqa: F811
    item = svc.create_item(db, ws["tenant"].id, kind="post", title="x", actor_id=None, payload={"caption": "x"})
    db.commit()
    assert client.get(f"{BASE}/content/{item.id}/tracking", headers=ws["mkt_h"]).json()["code"].startswith("c-")
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    seed_capabilities(db, other.id)
    enable_module(db, other.id)
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    assert client.get(f"{BASE}/content/{item.id}/tracking", headers=other_h).status_code == 404


# ── Weekly report ───────────────────────────────────────────────────────────────────────────────────────────────────

def _ad_week(db, tid, ad, start: date, *, impressions=3000, reach=1500, clicks=60, spend=1000, chats=8, views=900,
             thru=300):
    for i in range(7):
        db.add(AdMetric(tenant_id=tid, ad_account_id="act", date=start + timedelta(days=i), ad_id=ad, ad_name=ad,
                        campaign_id="C1", campaign_name="Diwali", spend=Decimal(spend) / 7, impressions=impressions // 7,
                        reach=reach // 7, clicks=clicks // 7, link_clicks=clicks // 7, conversations_started=chats // 7 + (i == 0) * (chats % 7),
                        video_views=views // 7, video_thruplays=thru // 7))
    db.commit()


def test_report_facts_funnel_leaderboard_and_grounded_text(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    _ad_week(db, tid, "AD1", date(2026, 10, 12))
    g, inq = _lead(db, tid)
    _chat(db, tid, g, inq, ad_id="AD1", at=datetime(2026, 10, 13, 6, tzinfo=timezone.utc))
    _stay(db, tid, inq)
    f = insights.facts(db, ws["tenant"], TODAY)
    assert f["period"] == {"from": "2026-10-12", "to": "2026-10-18"}
    assert f["funnel"]["ads"]["chats"] == 8 and f["funnel"]["ads"]["qualified"] == 1 and f["funnel"]["ads"]["bookings"] == 1
    assert f["funnel"]["ads"]["cost_per_booking"] == pytest.approx(1000, abs=1)
    top = f["ads"][0]
    assert top["ad_id"] == "AD1" and top["hook_rate"] and top["hold_rate"] and top["confidence"] != st.NOT_ENOUGH

    def fake(task, tenant_id, system, user, tool):
        assert task == "marketing_insights"
        return ({"headline": "Ads brought 8 chats. Revenue grew 999 percent.",
                 "explain": {"wins": ["One booking came from the Diwali ad."], "problems": [], "actions": []}},
                {"model": "m"}, "nvidia")
    with patch.object(ai, "_call", side_effect=fake):
        row = report.generate(db, ws["tenant"], today=TODAY)
    db.commit()
    assert row.kind == "marketing_insights" and row.brief_source == "llm"
    assert row.brief["headline"] == "Ads brought 8 chats."                   # the invented 999 sentence is dropped
    assert row.validation["dropped"][0]["numbers"] == ["999"]
    again = report.generate(db, ws["tenant"], today=TODAY)                   # one report per week
    assert again.id == row.id


def test_report_without_the_ai_is_deterministic_and_says_not_enough_data(db, ws):  # noqa: F811
    with patch.object(ai, "_call", side_effect=ai.LLMTransientError("down")):
        row = report.generate(db, ws["tenant"], today=TODAY)
    assert row.brief_source == "deterministic" and row.brief["headline"]
    assert row.facts["elements"]["posts"]["fields"] == {} and row.facts["ads"] == []


def test_report_feeds_the_next_plan(db, ws):  # noqa: F811
    from app.models.analyst import AnalystReport
    db.add(AnalystReport(tenant_id=ws["tenant"].id, kind="marketing_insights", period_start=date(2026, 10, 12),
                         period_end=date(2026, 10, 18), facts={"next_plan": {"do_more": [{"what": "Hook: pov (posts)"}],
                                                                               "stop": [], "test": []}}))
    db.commit()
    assert "Hook: pov" in insights.for_plan(db, ws["tenant"].id)


def test_insights_api_roles_and_isolation(client, db, ws):  # noqa: F811
    with patch.object(ai, "_call", side_effect=ai.LLMTransientError("down")):
        report.generate(db, ws["tenant"])
    db.commit()
    assert client.get(f"{BASE}/insights", headers=ws["mkt_h"]).status_code == 403          # money: approvers only
    r = client.get(f"{BASE}/insights", headers=ws["manager_h"])
    assert r.status_code == 200 and r.json()["report"]["period"]["from"]
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    seed_capabilities(db, other.id)
    enable_module(db, other.id)
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    assert client.get(f"{BASE}/insights", headers=other_h).json() == {"report": None}


def test_analyst_report_list_leaves_out_marketing_insights(db, ws):  # noqa: F811
    from app.services.analyst import reports as analyst_reports
    with patch.object(ai, "_call", side_effect=ai.LLMTransientError("down")):
        report.generate(db, ws["tenant"], today=TODAY)
    db.commit()
    assert analyst_reports.list_reports(db, ws["tenant"].id) == []


def test_tick_queues_monday_from_eight_once(db, ws, monkeypatch):  # noqa: F811
    from app.workers.tasks import marketing_insights as tasks
    monkeypatch.setattr("app.core.tenant_tz.get_tenant_now", lambda t: datetime(2026, 10, 19, 7, 0))
    assert ws["tenant"].id not in tasks.due(db)                          # Monday before 08:00
    monkeypatch.setattr("app.core.tenant_tz.get_tenant_now", lambda t: datetime(2026, 10, 19, 9, 0))
    assert ws["tenant"].id in tasks.due(db)
    with patch.object(ai, "_call", side_effect=ai.LLMTransientError("down")):
        report.generate(db, ws["tenant"], today=date(2026, 10, 19))
    db.commit()
    assert ws["tenant"].id not in tasks.due(db)                          # once per week
