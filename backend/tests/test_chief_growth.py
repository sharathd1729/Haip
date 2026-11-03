"""AI Executive E3: marketing, social, reviews, ads, website, partnerships and webhook detectors, and the plans that act on
them (post-wide comment DM rule, Studio weekly run, review reply drafts, website DRAFT changes). Every external call
(Celery, Meta, the website AI) is patched: nothing leaves."""

import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

from app.models.automation import AutomationRule
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.inquiry import Inquiry, InquirySource
from app.models.insight import Insight
from app.models.marketing import MarketingGuestReview
from app.models.task import Task
from app.models.webhook import WebhookEndpoint
from app.models.website import SitePageView
from app.services import booking_agenda_service, ig_keyword_match
from app.services.chief import detectors, executor, plans, plans_growth
from app.services.chief import detectors_growth as g
from tests.analyst_world import world

ON = {"chief": {"enabled": True}}
PUSH = "app.services.push_service.send_to_tenant"
SITE = "app.services.chief.detectors_growth.site_v2"


def _ctx(db, w):
    return detectors.Ctx(db, w.t)


def _finding(db, w, hit, code, role):
    row = Insight(
        tenant_id=w.t.id,
        category_code=code,
        target_id=hit["target_id"],
        category="revenue",
        role=role,
        severity=hit["severity"],
        title=hit["title"],
        body=hit["body"],
        numbers=hit["numbers"],
        evidence=hit["evidence"],
    )
    db.add(row)
    db.commit()
    return row


def _approve_and_run(db, w, p):
    executor.approve(db, w.t, p, w.owner.id, p.plan_sha)
    db.commit()
    with patch(PUSH):
        return executor.run(db, w.t, p)


def _comments(db, w, media, n):
    conv = Conversation(
        id=str(uuid.uuid4()), tenant_id=w.t.id, guest_id=w.guests[0].id, channel=ChannelType.INSTAGRAM, is_open=True
    )
    db.add(conv)
    db.flush()
    for i in range(n):
        db.add(
            Message(
                id=str(uuid.uuid4()),
                tenant_id=w.t.id,
                conversation_id=conv.id,
                direction=MessageDirection.INBOUND,
                channel=ChannelType.INSTAGRAM,
                body=f"price? {i}",
                channel_metadata={"source": "comment", "comment_id": f"c{i}", "media_id": media},
            )
        )
    db.commit()


def test_comment_spike_becomes_a_post_wide_dm_rule(db):
    w = world(db, brand_config=ON)
    _comments(db, w, "media-1", 12)
    _comments(db, w, "media-2", 4)
    hits = g.social_comment_spike(_ctx(db, w))
    assert [h["target_id"] for h in hits] == ["media-1"] and hits[0]["numbers"] == {"comments": 12}
    _finding(db, w, hits[0], "MK1", "social_media")
    p = plans.propose_for_tenant(db, w.t)[0]
    dm, public = plans_growth.comment_texts(w.t)
    assert p.risk_tier == "R3" and any(dm in line for line in p.preview) and "price" not in dm.lower()
    try:
        executor.approve(db, w.t, p, w.owner.id, p.plan_sha, via="whatsapp")
        raise AssertionError("public replies approved on WhatsApp")
    except executor.DecisionError as exc:
        assert exc.status == 403
    assert _approve_and_run(db, w, p) == "done"
    rule = ig_keyword_match.find_matching_rule(db, w.t.id, "ig_comment_received", "how much?", media_id="media-1")
    assert (
        rule is not None and rule.action_config["message"] == dm and rule.action_config["public_ack_pool"] == [public]
    )
    assert g.social_comment_spike(_ctx(db, w)) == []  # covered now


def test_reviews_without_reply_get_ai_drafts_a_person_posts(db):
    w = world(db, brand_config=ON)
    old = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    rows = [
        MarketingGuestReview(
            id=str(uuid.uuid4()),
            tenant_id=w.t.id,
            external_id=f"g{i}",
            rating=r,
            comment="ok",
            reviewed_at=old,
            reply_status="none",
        )
        for i, r in enumerate((5, 2))
    ]
    db.add_all(rows)
    db.commit()
    hit = g.reviews_unanswered(_ctx(db, w))[0]
    assert hit["numbers"] == {"reviews": 2, "low_rated": 1} and hit["severity"] == "high"
    _finding(db, w, hit, "MK7", "guest_relations")
    p = plans.propose_for_tenant(db, w.t)[0]
    assert p.risk_tier == "R1"
    with patch("app.workers.tasks.marketing_studio.draft_review_reply.delay") as d:
        assert _approve_and_run(db, w, p) == "done"
    assert sorted(c.args[1] for c in d.call_args_list) == sorted(r.id for r in rows)


def test_ad_spend_with_no_leads_is_a_recommendation_only(db):
    w = world(db, brand_config=ON)

    class Row:
        config = {"ad_account_id": "act_1"}

    summary = {
        "campaigns": [
            {"campaign_id": "c1", "campaign_name": "Goa reels", "spend": 2500.0, "haip_leads": 0},
            {"campaign_id": "c2", "campaign_name": "Coorg", "spend": 9000.0, "haip_leads": 3},
        ]
    }
    with (
        patch("app.services.meta_ads_service.get_row", return_value=Row()),
        patch("app.services.meta_ads_service.summary", return_value=summary),
    ):
        hits = g.ads_spend_no_leads(_ctx(db, w))
    assert [h["target_id"] for h in hits] == ["c1"] and hits[0]["numbers"] == {"spend": 2500, "leads": 0}
    _finding(db, w, hits[0], "MK2", "ads_analyst")
    assert plans.propose_for_tenant(db, w.t) == []  # ads are read-only: no plan, a person acts


def test_cadence_drop_starts_a_studio_run_unless_paused(db):
    w = world(db, brand_config=ON)
    with (
        patch("app.services.marketing_agency_run.module_enabled", return_value=True),
        patch("app.services.marketing_reports._published", side_effect=[1, 6]),
    ):
        hit = g.marketing_cadence_drop(_ctx(db, w))[0]
    assert hit["numbers"] == {"last_14_days": 1, "previous_14_days": 6}
    row = _finding(db, w, hit, "MK4", "marketing_manager")
    w.t.brand_config = {**ON, "marketing_studio": {"agency": {"paused": True}}}
    assert plans.propose_for_tenant(db, w.t) == []
    w.t.brand_config = ON
    p = next(x for x in plans.propose_for_tenant(db, w.t) if x.finding_id == row.id)
    with patch("app.workers.tasks.marketing_studio.agency_run_week.delay") as run:
        assert _approve_and_run(db, w, p) == "done"
    assert run.call_args.args == (w.t.id, "chief", w.owner.id)


def test_more_visits_fewer_enquiries_drafts_a_website_change(db):
    w = world(db, brand_config=ON)
    today = booking_agenda_service.tenant_today(db, w.t.id)
    site_id = str(uuid.uuid4())
    for d, v in ((today - timedelta(days=10), 150), (today - timedelta(days=3), 300)):
        db.add(SitePageView(tenant_id=w.t.id, site_id=site_id, day=d.isoformat(), path="/", source="direct", views=v))
    for d, n in ((today - timedelta(days=10), 4), (today - timedelta(days=3), 1)):
        for _ in range(n):
            db.add(
                Inquiry(
                    id=str(uuid.uuid4()),
                    tenant_id=w.t.id,
                    guest_id=w.guests[0].id,
                    source=InquirySource.WEBSITE,
                    created_at=datetime.combine(d, datetime.min.time(), tzinfo=UTC) + timedelta(hours=10),
                )
            )
    db.commit()
    with patch(SITE, return_value=None):
        assert g.website_traffic_not_converting(_ctx(db, w)) == []  # no v2 site: nothing to change
    with patch(SITE, return_value=object()):
        hit = g.website_traffic_not_converting(_ctx(db, w))[0]
        assert hit["numbers"] == {"visits": 300, "visits_before": 150, "enquiries": 1, "enquiries_before": 4}
        _finding(db, w, hit, "WB1", "website")
        p = plans.propose_for_tenant(db, w.t)[0]
    assert p.risk_tier == "R1" and p.steps[0]["args"]["text"] == plans_growth.WB1_TEXT

    class Job:
        id = "job-1"

    with (
        patch("app.services.website_service.get_site", return_value=object()),
        patch("app.services.website_change.request", return_value=Job()) as req,
        patch("app.workers.tasks.website.builder_step.delay") as step,
    ):
        assert _approve_and_run(db, w, p) == "done"
    assert req.call_args.args[3] == plans_growth.WB1_TEXT and step.call_args.args == (w.t.id, "job-1")


def test_free_long_weekend_suggests_a_section_without_a_price(db):
    w = world(db, brand_config=ON)
    start = date.today() + timedelta(days=30)
    lw = [{"start": start.isoformat(), "end": (start + timedelta(days=2)).isoformat(), "days": 3, "reason": "Diwali"}]
    free = {w.prop.id: [start + timedelta(days=i) for i in range(3)]}
    with (
        patch(SITE, return_value=object()),
        patch("app.services.marketing_demand.long_weekends", return_value=lw),
        patch("app.services.marketing_demand.free_nights", return_value=free),
    ):
        hit = g.website_peak_weekend(_ctx(db, w))[0]
        assert hit["numbers"] == {"free_pct": 100, "days": 3} and hit["target_id"] == start.isoformat()
        _finding(db, w, hit, "WB3", "website")
        p = plans.propose_for_tenant(db, w.t)[0]
    text = p.steps[0]["args"]["text"]
    assert "Diwali" in text and "Do not mention any price" in text and "Rs" not in text


def test_drafts_partnerships_and_webhooks(db):
    w = world(db, brand_config=ON)
    with (
        patch(SITE, return_value=object()),
        patch(
            "app.services.website_autobuild.drafts",
            return_value=[{"id": "r1", "kind": "package", "key": "goa", "name": "Goa"}],
        ),
    ):
        assert g.website_drafts_unpublished(_ctx(db, w))[0]["numbers"] == {"drafts": 1}
    conv = Conversation(
        id=str(uuid.uuid4()), tenant_id=w.t.id, guest_id=w.guests[0].id, channel=ChannelType.INSTAGRAM, is_open=True
    )
    db.add(conv)
    db.add(
        Task(
            tenant_id=w.t.id,
            title="Collaboration request: reply yes or no — Asha",
            priority="high",
            conversation_id=conv.id,
            created_at=datetime.now(UTC) - timedelta(days=2),
        )
    )
    db.add(
        Task(
            tenant_id=w.t.id,
            title="Collaboration request: reply yes or no — Ravi",
            priority="high",
            created_at=datetime.now(UTC) - timedelta(hours=2),
        )
    )
    for n in (12, 3):
        db.add(
            WebhookEndpoint(
                tenant_id=w.t.id,
                url="https://example.com/h",
                secret_enc=b"x",
                events=["booking.created"],
                is_active=True,
                consecutive_failures=n,
            )
        )
    db.commit()
    hit = g.partnerships_unanswered(_ctx(db, w))[0]
    assert hit["numbers"] == {"waiting": 1} and hit["evidence"][0]["id"] == conv.id
    hooks = g.api_webhooks_failing(_ctx(db, w))
    assert len(hooks) == 1 and hooks[0]["numbers"]["failures"] == 12


def test_growth_detectors_run_in_the_catalogue_and_stay_in_their_tenant(db):
    from app.services.chief import findings

    a, b = world(db, brand_config=ON), world(db, brand_config=ON)
    _comments(db, a, "media-9", 11)
    findings.run(db, a.t, "urgent")
    findings.run(db, b.t, "urgent")
    db.commit()
    assert db.query(Insight).filter_by(tenant_id=a.t.id, category_code="MK1", is_auto_resolved=False).count() == 1
    assert db.query(Insight).filter_by(tenant_id=b.t.id, category_code="MK1").count() == 0
    assert db.query(AutomationRule).filter_by(tenant_id=a.t.id).count() == 0  # detection never acts


def test_the_full_daily_pass_runs_every_detector_without_a_failure(db):
    from app.services.chief import catalogue, findings

    w = world(db, brand_config=ON)
    out = findings.run(db, w.t, "daily")
    assert out["failed"] == [] and out["ran"] == len(catalogue.CATALOGUE)
