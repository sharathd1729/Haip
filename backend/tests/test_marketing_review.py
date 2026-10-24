"""Agency M1 (21 Oct 2026): deterministic draft checks, brand review, one rewrite, held drafts, brand voice."""
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.models.marketing import MarketingCompetitor, MarketingContent, MarketingReview, MarketingTask
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import marketing_agency_run as runs
from app.services import marketing_agency_service as agency
from app.services import marketing_ai_service as ai
from app.services import marketing_content_service as svc
from app.services import marketing_lint as lint
from app.services import marketing_review_service as review
from tests.test_marketing_agency import AUDIT, _plan, _seed_insights
from tests.test_marketing_studio_content import BASE, make_user, seed_photos, ws  # noqa: F401  (fixture)

BAD = "It's not just a trip, it's a feeling.\nAgree?"
GOOD = "Monsoon in Coorg, from the caravan door. Coffee estates on both sides and nowhere to be by noon. DM us your dates."


def _rules(findings):
    return {f["rule"] for f in findings}


# ── Deterministic checks ────────────────────────────────────────────────────────────────────────────────────────────

def test_ai_tells_and_compliance_are_caught_with_where_and_quote():
    found = lint.check("post", {"caption": "Nestled in the hills, the best in Coorg. Guaranteed calm.\n" + BAD},
                       competitors=["@wildtrails"])
    assert {"contrast_reveal", "engagement_bait", "guarantee"} <= {f["rule"] for f in found if f["severity"] == "high"}
    assert {"stock_phrases", "superlative"} <= _rules(found)
    bait = next(f for f in found if f["rule"] == "engagement_bait")
    assert bait["where"] == "caption" and bait["quote"] == "Agree?"
    assert lint.check("post", {"caption": GOOD}) == []


def test_competitor_named_anywhere_blocks():
    found = lint.check("story", {"frames": [{"text": "Better than WildTrails, really"}]}, competitors=["@wildtrails"])
    assert [(f["rule"], f["where"]) for f in found if f["severity"] == "high"] == [("competitor_named", "frame 1")]


def test_numbers_must_come_from_the_facts_and_need_markers_block():
    payload = {"caption": "Sleeps 6 guests, 12 km from Madikeri. Check-in [NEED: check-in time]."}
    found = lint.check("post", payload, facts_text="{'max_adults': 4, 'distance': 12}")
    assert [f["rule"] for f in found if f["severity"] == "high"] == ["missing_fact", "unverified_number"]
    assert next(f for f in found if f["rule"] == "unverified_number")["quote"] == "6 guests"
    human = lint.check("post", payload, facts_text="12", strict_numbers=False)
    assert next(f for f in human if f["rule"] == "unverified_number")["severity"] == "medium"   # a person may know


def test_carousel_cover_count_and_caption_hook():
    slides = [{"headline": "5 reasons to wake up in Coorg"}, {"headline": "Mist"}, {"headline": "Chai"},
              {"headline": "Your turn", "body": "DM us your dates"}]
    found = lint.check("carousel", {"caption": "5 reasons to wake up in Coorg\nmore", "slides": slides})
    assert "count_mismatch" in {f["rule"] for f in found if f["severity"] == "high"}
    assert "caption_repeats_cover" in _rules(found)
    ok = [{"headline": "Three mornings in Coorg"}, {"headline": "Day 1"}, {"headline": "Day 2"}, {"headline": "Day 3"},
          {"headline": "Your turn", "body": "DM us"}]
    assert lint.check("carousel", {"caption": GOOD, "slides": ok, "framework": "itinerary"}) == []


def test_framework_is_validated_and_never_checked_as_guest_text(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    slides = [{"headline": "A"}, {"headline": "B"}]
    from app.schemas.marketing import strings_of, validate_content
    with pytest.raises(ValueError):
        validate_content("carousel", {"caption": "x", "slides": slides, "framework": "rant"})
    assert "guide" not in strings_of({"framework": "guide", "design": {"style": "panel", "colour": "#000000"}})
    item = svc.create_item(db, tid, kind="carousel", title="x", actor_id=ws["mkt"].id,
                           payload={"caption": "x", "slides": slides, "framework": "guide"})
    assert svc.get_version(db, tid, item.current_version_id).payload["framework"] == "guide"


# ── Brand voice in the profile ──────────────────────────────────────────────────────────────────────────────────────

def test_brand_voice_and_tone_round_trip_and_are_capped(client, ws):  # noqa: F811
    voice = [{"trait": "Warm", "we_are": "Warm and specific", "we_are_not": "Gushing", "sounds_like": "Chai at 7"}]
    r = client.put(f"{BASE}/profile", json={"voice": voice, "tone": "Warm, understated",
                                                     "channel_tone": {"instagram": "Unhurried, visual"}}, headers=ws["owner_h"])
    assert r.status_code == 200, r.text
    got = client.get(f"{BASE}/profile", headers=ws["mkt_h"]).json()
    got = got.get("profile", got)
    assert got["voice"][0]["we_are_not"] == "Gushing" and got["channel_tone"]["instagram"] == "Unhurried, visual"
    assert got["tone"] == "Warm, understated"                                  # the existing field is untouched
    r = client.put(f"{BASE}/profile", json={"voice": voice * 6}, headers=ws["owner_h"])
    assert r.status_code == 422


# ── Review rows ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_review_is_stored_per_text_and_kept_across_a_photo_only_version(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    item = svc.create_item(db, tid, kind="post", title="x", actor_id=None, payload={"caption": BAD})
    db.commit()
    row = review.current(db, ws["tenant"], item)
    assert row.blocking and {"contrast_reveal", "engagement_bait"} <= _rules(row.findings)
    svc.add_version(db, tid, item.id, {"caption": BAD, "design": {"style": "photo"}}, origin="ai", actor_id=None)
    db.commit()
    assert review.current(db, ws["tenant"], item).id == row.id                 # same text: same review
    svc.add_version(db, tid, item.id, {"caption": GOOD}, origin="human", actor_id=ws["mkt"].id)
    db.commit()
    fresh = review.current(db, ws["tenant"], item)
    assert fresh.id != row.id and not fresh.blocking
    assert db.query(MarketingReview).filter_by(tenant_id=tid).count() == 2


def test_ai_editor_adds_advice_capped_at_medium_with_known_labels(db, ws):  # noqa: F811
    item = svc.create_item(db, ws["tenant"].id, kind="post", title="x", actor_id=None, payload={"caption": GOOD})
    db.commit()
    seen = {}

    def fake(task, tenant_id, system, user, tool):
        seen.update(task=task, user=user)
        return {"summary": "Close.", "findings": [
            {"issue": "Too formal for the voice", "where": "caption", "severity": "medium", "quote": "Monsoon", "suggestion": "x"},
            {"issue": "Odd label", "where": "slide 9", "severity": "low"}]}, {"model": "m"}, "nvidia"
    with patch.object(ai, "_call", side_effect=fake):
        row = review.run_ai(db, ws["tenant"], item.id)
    assert seen["task"] == "marketing_review" and "[caption] Monsoon in Coorg" in seen["user"]
    assert row.ai_status == "ready" and row.summary == "Close." and row.prompt_version == "marketing-review-v3"
    assert [(a["severity"], a["where"]) for a in row.advice] == [("medium", "caption"), ("low", "caption")]
    with patch.object(ai, "_call", return_value=({"summary": "x", "findings": [{"issue": "y", "where": "caption",
                                                                                "severity": "high"}]}, {}, "nvidia")):
        row = review.run_ai(db, ws["tenant"], item.id)
    assert row.ai_status == "failed" and not row.blocking                     # the AI can never block


# ── Agency run: one rewrite, then held ──────────────────────────────────────────────────────────────────────────────

def _run_with(db, ws, captions, scores=None):  # noqa: F811
    """A run whose copywriter returns `captions` in turn for the single planned post; the critic returns `scores` in
    turn (agency M3), the last one repeating."""
    tid = ws["tenant"].id
    _seed_insights(db, tid)
    seed_photos(db, tid)
    start = datetime.now(ZoneInfo("Asia/Kolkata")).date() + timedelta(days=1)
    plan = _plan(start)
    plan["calendar"] = plan["calendar"][:1]
    queue = list(captions)
    briefs = []

    def fake(task, tenant_id, system, user, tool):
        if task == "marketing_audit":
            return dict(AUDIT), {"model": "m"}, "nvidia"
        if task == "marketing_plan":
            return plan, {"model": "m"}, "nvidia"
        if task == "marketing_review":
            marks = (scores.pop(0) if len(scores) > 1 else scores[0]) if scores else None
            return {"summary": "ok", "findings": [], **({"scores": marks} if marks else {})}, {"model": "m"}, "nvidia"
        briefs.append(user)
        return {"caption": queue.pop(0) if len(queue) > 1 else queue[0]}, {"model": "m"}, "nvidia"
    with patch.object(ai, "_call", side_effect=fake), patch.object(agency, "notify_needs_approval"):
        run_id = runs.run_week(db, tid, trigger="manual")
    item = db.query(MarketingContent).filter_by(tenant_id=tid).one()
    return run_id, item, briefs


def test_a_blocked_draft_is_rewritten_once_with_the_findings_and_then_submitted(db, ws):  # noqa: F811
    run_id, item, briefs = _run_with(db, ws, [BAD, GOOD])
    assert len(briefs) == 2 and "Agree?" in briefs[1] and "Write it again without them" in briefs[1]
    assert item.status == "in_review"
    draft = db.query(MarketingTask).filter_by(run_id=run_id, step="draft").one()
    assert draft.detail["rewritten"] == 1
    assert review.current(db, ws["tenant"], item).ai_status == "ready"


def test_a_draft_still_blocked_after_the_rewrite_is_held_not_submitted(db, ws):  # noqa: F811
    run_id, item, briefs = _run_with(db, ws, [BAD])
    assert len(briefs) == 2 and item.status == "draft"                        # exactly one rewrite, never a loop
    submit = db.query(MarketingTask).filter_by(run_id=run_id, step="submit").one()
    assert submit.status == "skipped" and submit.detail["held"] == 1 and "brand review" in submit.detail["reason"]
    assert agency.pending_approvals(db, ws["tenant"].id) == []


# ── API ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_review_api_roles_queue_and_tenant_scope(client, db, ws, monkeypatch):  # noqa: F811
    tid = ws["tenant"].id
    item = svc.create_item(db, tid, kind="post", title="x", actor_id=ws["mkt"].id, payload={"caption": BAD})
    db.commit()
    r = client.get(f"{BASE}/content/{item.id}/review", headers=ws["mkt_h"])
    assert r.status_code == 200 and r.json()["blocking"] is True and r.json()["status"] == "skipped"
    queued = []
    monkeypatch.setattr("app.workers.tasks.marketing_studio.review_content.delay", lambda *a: queued.append(a))
    _, foh_h = make_user(db, tid, UserRole.FOH)
    assert client.post(f"{BASE}/content/{item.id}/review", headers=foh_h).status_code == 403
    r = client.post(f"{BASE}/content/{item.id}/review", headers=ws["mkt_h"])
    assert r.status_code == 202 and r.json()["status"] == "pending" and queued == [(tid, item.id)]

    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    theirs = svc.create_item(db, other.id, kind="post", title="t", actor_id=None, payload={"caption": BAD})
    db.commit()
    assert client.get(f"{BASE}/content/{theirs.id}/review", headers=ws["mkt_h"]).status_code == 404
    assert db.query(MarketingReview).filter_by(tenant_id=other.id).count() == 0


def test_queue_down_marks_the_ai_review_failed_but_keeps_the_checks(client, db, ws, monkeypatch):  # noqa: F811
    item = svc.create_item(db, ws["tenant"].id, kind="post", title="x", actor_id=ws["mkt"].id, payload={"caption": BAD})
    db.commit()

    def down(*a):
        raise ConnectionError("broker down")
    monkeypatch.setattr("app.workers.tasks.marketing_studio.review_content.delay", down)
    body = client.post(f"{BASE}/content/{item.id}/review", headers=ws["mkt_h"]).json()
    assert body["status"] == "failed" and "queue" in body["error"] and body["blocking"] is True


def test_a_person_sending_for_approval_queues_the_editor_and_approvals_show_counts(client, db, ws, monkeypatch):  # noqa: F811
    queued = []
    monkeypatch.setattr("app.workers.tasks.marketing_studio.review_content.delay", lambda *a: queued.append(a))
    photo = seed_photos(db, ws["tenant"].id, 1)[0]
    item = svc.create_item(db, ws["tenant"].id, kind="post", title="x", actor_id=ws["mkt"].id,
                           payload={"caption": "The best caravan in Coorg. " + GOOD, "media": {"asset_id": photo.id}})
    db.commit()
    r = client.post(f"{BASE}/content/{item.id}/submit", json={"version_id": item.current_version_id}, headers=ws["mkt_h"])
    assert r.status_code == 200 and queued == [(ws["tenant"].id, item.id)]
    row = client.get(f"{BASE}/approvals", headers=ws["mkt_h"]).json()["items"][0]
    assert row["review"] == {"high": 0, "medium": 1, "reviewed": True}


def test_competitors_from_research_are_checked(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    db.add(MarketingCompetitor(tenant_id=tid, handle="wildtrails", display_name="Wild Trails Caravans"))
    db.commit()
    item = svc.create_item(db, tid, kind="post", title="x", actor_id=None, payload={"caption": "Unlike Wild Trails Caravans, we wait."})
    db.commit()
    assert "competitor_named" in _rules(review.current(db, ws["tenant"], item).findings)
