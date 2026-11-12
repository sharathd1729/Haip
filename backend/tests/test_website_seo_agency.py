"""Website SEO agency (services/website_seo_agency.py, website_seo_roles.py, website_seo_fixes.py): each role's weekly
step with the LLM mocked, autonomy (asks-first never publishes), Get found steps for a person, guardrails (no outbound
call to another platform, no paid-link wording), the kill switch, the Monday rule, the AI Executive's SEO1, the API
(happy, wrong role, cross-tenant) and tenant isolation."""

import hashlib
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import httpx
import pytest

from app.models.audit_event import AuditEvent
from app.models.google_surfaces import GscSearchRow
from app.models.marketing import MarketingContent, MarketingGuestReview, MarketingTask
from app.models.marketing_partners import MarketingCreator
from app.models.media_asset import MediaAsset
from app.models.sop import SopStepProgress
from app.models.tenant import Tenant
from app.schemas.sops import StartIn
from app.services import marketing_ai_service as ai
from app.services import website_seo_agency as agency
from app.services import website_seo_fixes as fixes
from app.services import website_seo_roles as roles
from app.services.sops import generate
from app.services.sops import service as sops
from app.services.website_service import WebsiteError
from tests.test_website_v2_booking import _spec
from tests.website_fixtures import BASE, make_tenant, publish_live, wsite  # noqa: F401

TODAY = date(2026, 11, 9)  # a Monday


@pytest.fixture(autouse=True)
def _no_rate_limit():
    with patch("app.middleware.rate_limit._check_limit", return_value=(True, 0)):
        yield


@pytest.fixture()
def calls(monkeypatch):
    """The LLM, mocked: records (task, system, user) and answers per task."""
    seen, answers = [], {}

    def fake(task, tenant_id, system, user, tool):
        seen.append({"task": task, "tenant_id": tenant_id, "system": system, "user": user})
        return answers.get(task, {}), {}, "gemini"

    monkeypatch.setattr(ai, "_call", fake)
    return type("C", (), {"seen": seen, "answers": answers})()


def _t(db, w) -> Tenant:
    return db.get(Tenant, w["tenant"].id)


def _ctx(db, w, today=TODAY):
    return roles.Ctx(db=db, tenant=_t(db, w), today=today)


def _gsc(db, tid, query, clicks, imps, day, page="https://x.example/"):
    db.add(
        GscSearchRow(
            tenant_id=tid,
            property="p",
            day=day,
            query=query,
            page=page,
            country="ind",
            device="MOBILE",
            clicks=clicks,
            impressions=imps,
            position=5.0,
            row_key=hashlib.sha256(f"{tid}|{query}|{day}|{page}".encode()).hexdigest(),  # VARCHAR(64), as the sync writes it
        )
    )


def _v2(client, w):
    r = client.post(f"{BASE}/draft/v2", json={"spec": _spec()}, headers=w["owner_h"])
    assert r.status_code == 201, r.text
    vid = r.json()["version"]["id"]
    assert (
        client.post(f"{BASE}/versions/{vid}/publish", json={"version_id": vid}, headers=w["owner_h"]).status_code == 200
    )


# ── settings ────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_defaults_follow_the_doc_and_asks_first_roles_cannot_act_alone(db, wsite):  # noqa: F811
    t = _t(db, wsite)
    s = agency.get_settings(t)
    assert s == {
        "paused": False,
        "roles": {
            "search_analyst": "autopilot",
            "content_writer": "suggest",
            "technical_checker": "autopilot",
            "local_profile": "suggest",
            "listings": "suggest",
            "links_citations": "suggest",
            "ads_analyst": "suggest",
        },
    }
    with pytest.raises(WebsiteError) as e:
        agency.update_settings(db, t, wsite["owner"].id, roles={"content_writer": "autopilot"})
    assert e.value.code == "level_too_high"
    agency.update_settings(db, t, wsite["owner"].id, roles={"ads_analyst": "off"}, paused=True)
    db.commit()
    assert agency.level(t, "search_analyst") == "off"  # kill switch turns every role off
    assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="website.seo_agency_changed").count() == 1


# ── roles ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_search_analyst_brief_keeps_only_grounded_sentences_and_caches_facts_first(db, wsite, calls):  # noqa: F811
    tid = wsite["tenant"].id
    for d in range(3, 10):
        _gsc(db, tid, "caravan coorg", 4, 60, TODAY - timedelta(days=d))
        _gsc(db, tid, "villa madikeri", 0, 40, TODAY - timedelta(days=d))
    for d in range(31, 38):
        _gsc(db, tid, "villa madikeri", 2, 40, TODAY - timedelta(days=d))
    db.commit()
    calls.answers["seo_brief"] = {
        "summary": "Searches for caravan coorg grew to 28 clicks. Bookings jumped 900%.",
        "actions": ["Write a guide.", "Raise prices by 37%."],
    }
    out = roles.search_analyst(_ctx(db, wsite), "autopilot")
    assert out["facts"]["searches_rising"][0] == {"query": "caravan coorg", "clicks": 28, "previous": 0}
    assert out["facts"]["searches_falling"][0]["query"] == "villa madikeri"
    assert out["brief"] == "Searches for caravan coorg grew to 28 clicks."  # 900% is not a fact: dropped
    assert out["actions"] == ["Write a guide."] and out["dropped"] == 2
    c = calls.seen[0]
    assert c["task"] == "seo_brief" and c["tenant_id"] == tid
    assert (
        "BUSINESS FACTS" in c["system"] and "caravan coorg" not in c["system"]
    )  # weekly numbers stay in the user part


def test_search_analyst_without_data_says_so_and_calls_no_model(db, wsite, calls):  # noqa: F811
    out = roles.search_analyst(_ctx(db, wsite), "autopilot")
    assert "Connect Search Console" in out["brief"] and calls.seen == []


def test_content_writer_drafts_guides_that_wait_for_a_person_once_per_search(db, wsite, calls):  # noqa: F811
    tid = wsite["tenant"].id
    t = _t(db, wsite)
    t.brand_name = "Greengoose Stays"
    for d in range(3, 6):
        _gsc(db, tid, "things to do in coorg", 0, 40, TODAY - timedelta(days=d))
        _gsc(db, tid, "greengoose stays coorg", 0, 90, TODAY - timedelta(days=d))  # the brand: never a guide
        _gsc(db, tid, "coorg homestay", 9, 60, TODAY - timedelta(days=d))  # clicks fine
    db.commit()
    out = roles.content_writer(_ctx(db, wsite), "suggest")
    assert [d["query"] for d in out["drafts"]] == ["things to do in coorg"]
    assert out["_queue"] == [("website.blog_draft", [tid, out["drafts"][0]["id"], "Things to do in coorg"])]
    item = db.get(MarketingContent, out["drafts"][0]["id"])
    assert item.kind == "article" and item.status == "draft" and item.approved_version_id is None
    db.add(
        MarketingTask(
            tenant_id=tid,
            run_id="r",
            role="seo_content_writer",
            step="weekly",
            status="done",
            trigger="schedule",
            detail=out,
        )
    )
    db.commit()
    assert roles.content_writer(_ctx(db, wsite), "suggest")["drafts"] == []  # not again next week


def test_technical_checker_fixes_only_what_haip_draws_and_suggest_changes_nothing(client, db, wsite):  # noqa: F811
    tid = wsite["tenant"].id
    db.add(
        MediaAsset(
            tenant_id=tid,
            storage_key="k",
            mime_type="image/jpeg",
            bytes=1,
            sha256="0" * 64,
            status="active",
            alt_text="",
            tags={"description": "A caravan parked under coffee trees"},
        )
    )
    db.commit()
    _v2(client, wsite)
    site = roles.Ctx(db=db, tenant=_t(db, wsite), today=TODAY).site()
    out = roles.technical_checker(_ctx(db, wsite), "suggest")
    assert out["fixes"]["alt"][0]["text"] == "A caravan parked under coffee trees"
    assert out["fixes"]["titles"][0]["slug"] == "/" and out["fixes"]["titles"][0]["title"].startswith("Home | ")
    assert "applied" not in out and db.query(MediaAsset).filter_by(tenant_id=tid).one().alt_text == ""
    assert any(p["key"] == "titles" for p in out["problems"])
    live_before = site.live_version_id
    out = roles.technical_checker(_ctx(db, wsite), "autopilot")
    assert out["applied"]["alt"] == 1 and out["applied"]["titles"] == 1
    db.refresh(site)
    assert site.live_version_id == live_before  # titles go to the draft; a person publishes
    assert db.query(MediaAsset).filter_by(tenant_id=tid).one().alt_text == "A caravan parked under coffee trees"
    assert fixes.plan(db, _t(db, wsite), site) == {"alt": [], "titles": []}


def test_local_profile_lists_steps_for_a_person_and_only_drafts_review_replies(db, wsite):  # noqa: F811
    t = _t(db, wsite)
    inst = sops.start(db, t, StartIn(template_key="gbp_setup"), wsite["owner"].id)
    generate.make_version(db, t, inst, reason="first", actor_id=wsite["owner"].id, use_ai=False)
    db.add(
        MarketingGuestReview(
            tenant_id=t.id,
            source="google",
            external_id="r1",
            reviewer="Priya",
            rating=5,
            comment="Lovely stay",
            reviewed_at="2026-11-01",
        )
    )
    db.commit()
    out = roles.local_profile(_ctx(db, wsite, today=date.today()), "suggest")
    assert (
        out["running"][0]["id"] == inst.id and out["steps"] and all(s["instance_id"] == inst.id for s in out["steps"])
    )
    assert {a["template_key"] for a in out["to_start"]} >= {"gbp_upkeep", "reviews_reply"}
    rid = db.query(MarketingGuestReview.id).filter_by(tenant_id=t.id).scalar()
    assert out["_queue"] == [("marketing_studio.draft_review_reply", [t.id, rid])]
    assert db.get(MarketingGuestReview, rid).reply_status == "none"  # nothing posted, nothing changed


def test_listings_and_links_offer_their_checklists(db, wsite):  # noqa: F811
    keys = {a["template_key"] for a in roles.listings(_ctx(db, wsite), "suggest")["to_start"]}
    assert any(k.endswith("_listing") for k in keys)
    assert [a["template_key"] for a in roles.links_citations(_ctx(db, wsite), "suggest")["to_start"]] == [
        "links_citations"
    ]


def test_links_outreach_never_offers_money_and_needs_creators(client, db, wsite, calls):  # noqa: F811
    tid = wsite["tenant"].id
    out = roles.links_citations(_ctx(db, wsite), "suggest")
    assert out["outreach"] == [] and "creators" in out["outreach_note"]
    db.add_all(
        [
            MarketingCreator(tenant_id=tid, handle="coorg.diaries", platform="instagram"),
            MarketingCreator(tenant_id=tid, handle="roadtrip.ria", platform="instagram"),
        ]
    )
    db.commit()
    publish_live(client, wsite)
    calls.answers["seo_outreach"] = {
        "messages": [
            {"handle": "coorg.diaries", "text": "Loved hosting you! Could you add our website to your Coorg post?"},
            {"handle": "roadtrip.ria", "text": "We will pay ₹2,000 for a dofollow link."},
        ]
    }
    out = roles.links_citations(_ctx(db, wsite), "suggest")
    by = {m["handle"]: m for m in out["outreach"]}
    assert by["coorg.diaries"]["ai"] and "https://" in by["coorg.diaries"]["text"]  # the site link is added by code
    assert not by["roadtrip.ria"]["ai"] and "pay" not in by["roadtrip.ria"]["text"].lower()
    assert "₹" not in by["roadtrip.ria"]["text"]


def test_ads_analyst_suggests_with_the_rupee_effect(db, wsite):  # noqa: F811
    fake = {
        "since": "2026-10-10",
        "until": "2026-11-08",
        "totals": {"spend": 9000, "bookings": 3, "revenue": 60000, "roas": 6.7, "cost_per_booking": 3000},
        "campaigns": [
            {"campaign_name": "Coorg weekend", "spend": 5000, "bookings": 3, "roas": 12.0},
            {"campaign_name": "Brand awareness", "spend": 4000, "bookings": 0, "roas": 0},
        ],
    }
    with patch("app.services.meta_ads_service.summary", return_value=fake):
        out = roles.ads_analyst(_ctx(db, wsite), "suggest")
    by = {s["campaign"]: s for s in out["suggestions"]}
    assert by["Brand awareness"] == {
        "campaign": "Brand awareness",
        "action": "pause",
        "effect_inr": 4000,
        "why": "Spent ₹4,000 in 30 days with no booking traced to it.",
    }
    assert by["Coorg weekend"]["extra_spend_inr"] == 1000 and by["Coorg weekend"]["effect_inr"] == 12000
    assert out["google_ads"] == "not_in_haip"


# ── the weekly run ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_weekly_run_records_every_role_never_calls_another_platform_and_publishes_nothing(
    client,
    db,
    wsite,  # noqa: F811
    calls,
    monkeypatch,
):
    def no_network(*a, **k):
        raise AssertionError("the SEO agency must not call another platform")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    monkeypatch.setattr(httpx.AsyncClient, "send", no_network)
    t = _t(db, wsite)
    run, queue = agency.run_week(db, t, trigger="manual", actor_id=wsite["owner"].id)
    db.commit()
    rows = db.query(MarketingTask).filter_by(tenant_id=t.id, run_id=run.run_id, step="weekly").all()
    assert {r.role for r in rows} == {f"seo_{r}" for r in agency.ORDER}
    assert all(r.status == "done" for r in rows), [(r.role, r.error) for r in rows]
    assert run.detail["roles"]["content_writer"] == "done"
    assert (
        db.query(MarketingContent)
        .filter(MarketingContent.tenant_id == t.id, MarketingContent.status.in_(("approved", "published")))
        .count()
        == 0
    )
    assert db.query(AuditEvent).filter_by(tenant_id=t.id, action="website.seo_agency_run").count() == 1
    parent, by_role = agency.last_run(db, t.id)
    assert parent.id == run.id and set(by_role) == set(agency.ORDER)


def test_kill_switch_stops_the_run_and_off_roles_are_skipped(db, wsite, calls):  # noqa: F811
    t = _t(db, wsite)
    agency.update_settings(db, t, wsite["owner"].id, roles={"ads_analyst": "off"})
    run, _ = agency.run_week(db, t, trigger="manual", actor_id=None)
    ads = db.query(MarketingTask).filter_by(run_id=run.run_id, role="seo_ads_analyst").one()
    assert ads.status == "skipped" and ads.detail["reason"] == "off"
    agency.update_settings(db, t, wsite["owner"].id, paused=True)
    with pytest.raises(WebsiteError) as e:
        agency.run_week(db, t, trigger="manual", actor_id=None)
    assert e.value.status == 409


def test_runs_on_monday_from_nine_once_a_week(db, wsite):  # noqa: F811
    t = _t(db, wsite)
    monday_nine = datetime(2026, 11, 9, 9, 5, tzinfo=UTC)
    with patch.object(agency, "get_tenant_now", return_value=monday_nine - timedelta(hours=1)):
        assert agency.due(db, t) is False
    with patch.object(agency, "get_tenant_now", return_value=monday_nine):
        assert agency.due(db, t) is True
        db.add(
            MarketingTask(
                tenant_id=t.id,
                run_id="r",
                role="seo_agency",
                step="seo_run",
                status="done",
                trigger="schedule",
                created_at=monday_nine,
            )
        )
        db.commit()
        assert agency.due(db, t) is False
    other = make_tenant(db, "Nosite")
    with patch.object(agency, "get_tenant_now", return_value=monday_nine):
        assert agency.due(db, other) is True  # its own week, its own rows


def test_overdue_get_found_steps_become_an_executive_finding(db, wsite):  # noqa: F811
    from app.services.chief.detectors import Ctx
    from app.services.chief.detectors_growth import getfound_overdue

    t = _t(db, wsite)
    inst = sops.start(db, t, StartIn(template_key="gbp_setup"), wsite["owner"].id)
    db.commit()
    now = datetime.now(UTC)
    assert getfound_overdue(Ctx(db, t, now)) == []
    for p in db.query(SopStepProgress).filter_by(instance_id=inst.id):
        p.due_at = now - timedelta(days=25)
    db.commit()
    hit = getfound_overdue(Ctx(db, t, now))[0]
    assert hit["severity"] == "high" and hit["numbers"]["oldest_days"] >= 24
    assert {"type": "sop_instance", "id": inst.id} in hit["evidence"]


# ── API ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_grow_endpoint_roles_and_money(client, db, wsite):  # noqa: F811
    r = client.get(f"{BASE}/grow", headers=wsite["owner_h"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert [p["key"] for p in body["score"]["parts"]] == ["setup", "technical", "found", "search"]
    assert body["score"]["total"] == 0 and body["last_run"] is None and len(body["roster"]) == 7
    assert any(t["kind"] == "start_checklist" and t["role"] == "links_citations" for t in body["tasks"])
    assert client.get(f"{BASE}/grow", headers=wsite["mkt_h"]).status_code == 200
    assert client.get(f"{BASE}/grow", headers=wsite["foh_h"]).status_code == 403
    assert client.put(f"{BASE}/seo-agency", json={"paused": True}, headers=wsite["mkt_h"]).status_code == 403
    assert client.post(f"{BASE}/seo-agency/run", headers=wsite["mkt_h"]).status_code == 403


def test_settings_run_and_fixes_endpoints(client, db, wsite):  # noqa: F811
    r = client.put(f"{BASE}/seo-agency", json={"roles": {"content_writer": "autopilot"}}, headers=wsite["owner_h"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "level_too_high"
    with patch("app.workers.tasks.website_seo_agency.run_week.delay") as d:
        assert client.post(f"{BASE}/seo-agency/run", headers=wsite["manager_h"]).status_code == 202
        d.assert_called_once_with(wsite["tenant"].id, "manual", wsite["manager"].id)
        assert client.put(f"{BASE}/seo-agency", json={"paused": True}, headers=wsite["owner_h"]).status_code == 200
        r = client.post(f"{BASE}/seo-agency/run", headers=wsite["owner_h"])
        assert r.status_code == 409 and r.json()["detail"]["code"] == "agency_paused"
        assert d.call_count == 1
    assert client.post(f"{BASE}/seo-agency/fixes/apply", headers=wsite["owner_h"]).status_code == 409
    r = client.patch(
        "/api/v1/tenants/me", json={"brand_config": {"seo_agency": {"paused": False}}}, headers=wsite["owner_h"]
    )
    assert r.status_code == 422


def test_another_workspace_never_sees_this_ones_run(client, db, wsite, calls, tenant_and_user):  # noqa: F811
    from app.models.user import UserRole
    from tests.test_marketing_studio_content import make_user

    other = make_tenant(db, "Elsewhere")
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    agency.run_week(db, _t(db, wsite), trigger="manual", actor_id=None)
    db.commit()
    assert agency.last_run(db, other.id) == (None, {})
    r = client.get(f"{BASE}/grow", headers=other_h)
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert r.json()["last_run"] is None
    assert db.query(MarketingTask).filter_by(tenant_id=other.id).count() == 0


def test_celery_tasks_are_routed_and_scheduled():
    from app.workers.celery_app import celery_app

    routes = celery_app.conf.task_routes
    assert routes["website_seo.orchestrate"]["queue"] == "default"
    assert routes["website_seo.run_week"]["queue"] == "default"
    beat = celery_app.conf.beat_schedule["website-seo-agency-orchestrate-hourly"]
    assert beat["task"] == "website_seo.orchestrate"
