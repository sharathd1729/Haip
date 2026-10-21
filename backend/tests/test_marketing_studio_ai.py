"""Marketing Studio AI runs, retries, usage metering, media library and migration 153's capability grants."""
import importlib.util
import io
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from app.models.capability import Capability, RoleCapability
from app.models.marketing import MarketingAudit, MarketingContent, MarketingContentVersion, MarketingPlan
from app.models.media_asset import MediaAsset
from app.models.usage_event import UsageEvent
from app.services import marketing_ai_service as ai
from app.services import marketing_content_service as svc
from app.services import media_library_service as media
from app.workers.tasks import marketing_studio as tasks

MEASURED = {"source": "instagram_graph_api", "available": True, "captured_at": "2026-10-17T06:30:00+00:00",
            "account": {"followers_count": 1200, "reach": 800}, "posts": []}
RAW = {"model": "openai/gpt-oss-20b", "input_tokens": 900, "output_tokens": 300}


def _llm(data, raw=RAW):
    return patch.object(ai, "_call", return_value=(data, raw, "nvidia"))


@pytest.fixture()
def tid(tenant_and_user):
    return tenant_and_user["tenant"].id


@pytest.fixture()
def item(db, tid, tenant_and_user):
    it = svc.create_item(db, tid, kind="post", title="Monsoon", actor_id=tenant_and_user["user"].id)
    db.commit()
    return it


# ── Content generation ──────────────────────────────────────────────────────────────────────────────────────────────

def test_generated_content_becomes_an_ai_version_and_is_metered(db, tid, item, tenant_and_user):
    with _llm({"kind": "post", "caption": "Rain on the windows, chai in hand.", "hashtags": ["monsoon"]}):
        ai.run_content(db, tid, item.id, tenant_and_user["user"].id, "monsoon mood")
    db.commit()
    v = db.query(MarketingContentVersion).filter_by(content_id=item.id).one()
    assert v.origin == "ai" and v.prompt_version == "marketing-content-v4" and v.payload["hashtags"] == ["#monsoon"]
    assert v.created_by == tenant_and_user["user"].id     # the requester counts as author for the self-approval rule
    ev = db.query(UsageEvent).filter_by(tenant_id=tid, ref_id=item.id).one()
    assert (ev.kind, ev.units, ev.input_units, ev.provider) == ("llm_tokens", 1200, 900, "nvidia")


def test_ai_output_that_breaks_the_schema_is_recorded_not_stored(db, tid, item):
    with _llm({"caption": ""}):
        ai.run_content(db, tid, item.id, None, None)
    db.commit()
    db.refresh(item)
    assert item.generation_status == "failed" and "format" in item.generation_error
    assert db.query(MarketingContentVersion).filter_by(content_id=item.id).count() == 0


def test_ai_price_mention_is_refused_in_handoff_workspace(db, tid, item):
    with _llm({"caption": "Only ₹9,999 a night!"}):
        ai.run_content(db, tid, item.id, None, None)
    db.commit()
    db.refresh(item)
    assert item.generation_status == "failed" and "price" in item.generation_error.lower()


def test_provider_error_that_is_not_transient_fails_once(db, tid, item):
    with patch("app.adapters.llm.get_llm") as get_llm:
        get_llm.return_value.complete.side_effect = RuntimeError("400 bad request")
        ai.run_content(db, tid, item.id, None, None)
    db.commit()
    db.refresh(item)
    assert item.generation_status == "failed" and "AI provider error" in item.generation_error


def test_transient_provider_error_is_raised_for_retry(db, tid, item):
    with patch("app.adapters.llm.get_llm") as get_llm:
        get_llm.return_value.complete.side_effect = TimeoutError("read timed out")
        with pytest.raises(ai.LLMTransientError):
            ai.run_content(db, tid, item.id, None, None)


def _fake_task(retries):
    class Retry(Exception):
        pass

    def retry(exc=None, countdown=None):
        t.countdown = countdown
        return Retry()

    t = SimpleNamespace(request=SimpleNamespace(retries=retries), retry=retry, Retry=Retry, countdown=None)
    return t


def _session():
    """A stand-in session: the task's rollback() must not touch the test database (SQLite would erase fixture rows)."""
    db = MagicMock()
    db.__enter__.return_value = db
    return db


def test_task_retries_transient_errors_with_backoff_then_gives_up():
    def transient(_db):
        raise ai.LLMTransientError("504 gateway timeout")

    db = _session()
    with patch("app.workers.tasks.marketing_studio.SessionLocal", return_value=db),          patch.object(ai, "mark_failed") as mark_failed:
        t = _fake_task(retries=1)
        with pytest.raises(t.Retry):
            tasks._run(t, "content", "t1", "row1", transient, MarketingContent)
        assert t.countdown == tasks.BASE_COUNTDOWN * 2
        mark_failed.assert_not_called()

        tasks._run(_fake_task(retries=tasks.MAX_RETRIES), "content", "t1", "row1", transient, MarketingContent)
    mark_failed.assert_called_once()
    assert mark_failed.call_args.args[1:4] == (MarketingContent, "row1", "t1")
    assert "unavailable" in mark_failed.call_args.args[4]
    db.rollback.assert_called()


def test_task_crash_never_leaves_row_pending():
    def crash(_db):
        raise KeyError("boom")

    db = _session()
    with patch("app.workers.tasks.marketing_studio.SessionLocal", return_value=db),          patch.object(ai, "mark_failed") as mark_failed:
        tasks._run(_fake_task(0), "content", "t1", "row1", crash, MarketingContent)
    mark_failed.assert_called_once()
    assert "KeyError" in mark_failed.call_args.args[4]
    db.commit.assert_called()


def test_mark_failed_sets_the_right_field(db, tid, item):
    ai.mark_failed(db, MarketingContent, item.id, tid, "gave up")
    db.commit()
    db.refresh(item)
    assert (item.generation_status, item.generation_error) == ("failed", "gave up")


# ── Audit + plan ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_audit_without_measured_data_fails_without_calling_ai(db, tid):
    a = MarketingAudit(tenant_id=tid, measured={"available": False}, status="pending")
    db.add(a)
    db.commit()
    with patch.object(ai, "_call") as call:
        ai.run_audit(db, tid, a.id)
    assert a.status == "failed" and "No Instagram insights" in a.error
    call.assert_not_called()


def test_audit_keeps_measured_and_ai_apart_and_drops_invented_metric_keys(db, tid):
    a = MarketingAudit(tenant_id=tid, measured=MEASURED, status="pending")
    db.add(a)
    db.commit()
    assessment = {"summary": "Reach is modest for the follower base.",
                  "findings": [{"area": "engagement", "observation": "Reach below followers.",
                                "metric_keys": ["reach", "followers_count", "made_up_metric"],
                                "recommendation": "Post reels twice a week."}]}
    with _llm(assessment):
        ai.run_audit(db, tid, a.id)
    db.commit()
    assert a.status == "ready" and a.measured == MEASURED
    assert a.assessment["findings"][0]["metric_keys"] == ["reach", "followers_count"]


def test_plan_calendar_is_clipped_to_the_period(db, tid):
    p = MarketingPlan(tenant_id=tid, period_start="2026-11-01", period_end="2026-11-30", status="pending")
    db.add(p)
    db.commit()
    body = {"goals": ["More DMs"], "audience": "Couples from Bengaluru", "pillars": ["Routes"], "cadence": "3 a week",
            "calendar": [{"date": "2026-11-05", "kind": "post", "pillar": "Routes", "idea": "Coorg loop"},
                         {"date": "2026-12-25", "kind": "story", "pillar": "Routes", "idea": "Out of range"}]}
    with _llm(body):
        ai.run_plan(db, tid, p.id)
    assert p.status == "ready" and [e["date"] for e in p.body["calendar"]] == ["2026-11-05"]


# ── Media library ───────────────────────────────────────────────────────────────────────────────────────────────────

def _png(w=1600, h=1200) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (30, 120, 90)).save(buf, format="PNG")
    return buf.getvalue()


def test_upload_is_reencoded_deduplicated_and_tenant_scoped(db, tid, tenant_and_user):
    stored = {}

    def fake_upload(tenant_id, content, mime, ext):
        key = f"{tenant_id}/marketing/{uuid.uuid4().hex}.{ext}"
        stored[key] = content
        return key

    with patch("app.services.media_storage.upload_marketing_media", side_effect=fake_upload):
        a = media.add_upload(db, tid, _png(), actor_id=tenant_and_user["user"].id)
        b = media.add_upload(db, tid, _png(), actor_id=tenant_and_user["user"].id)
    assert a.id == b.id and len(stored) == 1
    assert a.storage_key.startswith(f"{tid}/marketing/") and (a.width, a.height, a.mime_type) == (1600, 1200, "image/png")


@pytest.mark.parametrize("raw,code", [(b"", "empty_file"), (b"%PDF-1.4 not an image", "not_an_image"),
                                      (b"<svg onload=alert(1)></svg>", "not_an_image")])
def test_upload_rejects_non_images(db, tid, raw, code):
    with pytest.raises(media.MediaError) as exc:
        media.add_upload(db, tid, raw, actor_id=None)
    assert exc.value.code == code


def test_render_creative_makes_a_new_template_asset(db, tid, tenant_and_user):
    with patch("app.services.media_storage.upload_marketing_media", side_effect=lambda t, c, m, e: f"{t}/marketing/{uuid.uuid4().hex}.{e}"):
        src = media.add_upload(db, tid, _png(), actor_id=None)
        out = media.render_creative(db, tenant_and_user["tenant"], src.id, template="portrait_panel",
                                    headline="Monsoon in Coorg", subline="DM us to plan yours", actor_id=None,
                                    read_bytes=lambda key: _png())
    db.commit()
    assert out.source == "template" and (out.width, out.height) == (1080, 1350)
    assert out.provenance["from_asset_id"] == src.id
    assert db.query(UsageEvent).filter_by(tenant_id=tid, kind="creative_render").count() == 1


def test_render_refuses_another_tenants_asset(db, tid, tenant_and_user):
    other = MediaAsset(tenant_id=str(uuid.uuid4()), storage_key="x", mime_type="image/png", bytes=1, sha256="0" * 64)
    with pytest.raises(media.MediaError) as exc:
        media.render_creative(db, tenant_and_user["tenant"], other.id, template="square_panel", headline="Hi",
                              subline=None, actor_id=None, read_bytes=lambda k: _png())
    assert exc.value.code == "asset_not_found"


# ── Migration 153 grants ────────────────────────────────────────────────────────────────────────────────────────────

def _migration():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "153_marketing_studio.py"
    spec = importlib.util.spec_from_file_location("m129", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_grants_marketing_cells_once_and_never_edits_existing_rows(db, tid):
    m = _migration()
    db.query(RoleCapability).filter(RoleCapability.capability_key.like("marketing.%")).delete(synchronize_session=False)
    db.query(Capability).filter(Capability.key.like("marketing.%")).delete(synchronize_session=False)
    db.add(Capability(key="leads.read", label="x", category="leads")) if db.get(Capability, "leads.read") is None else None
    db.add(RoleCapability(id=str(uuid.uuid4()), tenant_id=tid, role="owner", capability_key="leads.read", allowed=True))
    db.commit()

    first = m.apply_capabilities(db.connection())
    db.commit()
    assert first["catalogue"] == 3 and first["cells"] == 3 * len(m._ROLES)
    granted = {(r.role, r.capability_key) for r in db.query(RoleCapability).filter_by(tenant_id=tid, allowed=True)
               if r.capability_key.startswith("marketing.")}
    assert ("manager", "marketing.approve") in granted and ("marketing", "marketing.approve") not in granted
    assert ("marketing", "marketing.edit") in granted and ("foh", "marketing.read") not in granted

    cell = db.query(RoleCapability).filter_by(tenant_id=tid, role="manager", capability_key="marketing.approve").one()
    cell.allowed = False      # an owner's later choice
    db.commit()
    again = m.apply_capabilities(db.connection())
    db.commit()
    assert again == {"catalogue": 0, "cells": 0}
    db.refresh(cell)
    assert cell.allowed is False


# ── v2 prompt data: median baseline, STOP/KEEP/TEST, stories, pillars, first comment ──────────────────────────────────

def test_baseline_is_the_accounts_own_median_and_each_posts_multiple():
    posts = [{"media_id": "a", "media_type": "IMAGE", "reach": 100, "saved": 2},
             {"media_id": "b", "media_type": "IMAGE", "reach": 300, "saved": 4},
             {"media_id": "c", "media_type": "CAROUSEL_ALBUM", "reach": 200, "saved": None}]
    b = ai.post_baseline(posts)
    assert b["enough_signal"] is True and b["medians"]["reach"] == 200.0
    assert b["medians"]["saved"] is None           # only two posts had saves: below MIN_POSTS_FOR_BASELINE
    assert {p["media_id"]: p["multiples"]["reach"] for p in b["by_post"]} == {"a": 0.5, "b": 1.5, "c": 1.0}
    assert b["by_media_type"]["IMAGE"]["posts"] == 2


def test_baseline_with_too_few_posts_says_so():
    b = ai.post_baseline([{"media_id": "a", "reach": 10}])
    assert b["enough_signal"] is False and all(v is None for v in b["medians"].values())


def test_audit_stores_stop_keep_test_and_open_questions(db, tid):
    a = MarketingAudit(tenant_id=tid, measured=MEASURED, status="pending")
    db.add(a)
    db.commit()
    with _llm({"summary": "s", "stop": ["Text-only quote cards"], "keep": ["Sunrise reels"], "test": ["Guest stories"],
               "not_enough_signal": ["Whether Tuesday posts do better"]}):
        ai.run_audit(db, tid, a.id)
    assert a.status == "ready"
    assert (a.assessment["stop"], a.assessment["keep"], a.assessment["test"]) == (["Text-only quote cards"], ["Sunrise reels"], ["Guest stories"])
    assert a.assessment["not_enough_signal"] == ["Whether Tuesday posts do better"]


@pytest.mark.parametrize("frames,ok", [
    ([{"text": "a", "sticker": {"type": "poll", "text": "Coorg or Ooty?", "options": ["Coorg", "Ooty"]}},
      {"text": "b", "sticker": {"type": "link", "text": "Plan yours"}}], True),
    ([{"sticker": {"type": "poll", "text": "x", "options": ["a", "b"]}}, {"sticker": {"type": "question", "text": "y"}}], False),
    ([{"sticker": {"type": "link", "text": "x"}}, {"sticker": {"type": "link", "text": "y"}}], False),
    ([{"sticker": {"type": "poll", "text": "x", "options": ["only one"]}}], False),
])
def test_story_allows_one_interaction_and_one_link(frames, ok):
    from pydantic import ValidationError
    from app.schemas.marketing import validate_content
    if ok:
        assert validate_content("story", {"frames": frames})["frames"][0]["sticker"]["type"] == "poll"
    else:
        with pytest.raises(ValidationError):
            validate_content("story", {"frames": frames})


def test_plan_refuses_six_pillars_and_calendar_pillars_outside_the_plan(db, tid):
    base = {"goals": ["g"], "audience": "a", "cadence": "c"}
    for body, needle in [({**base, "pillars": [f"P{i}" for i in range(6)]}, "format"),
                         ({**base, "pillars": ["Routes"], "calendar": [{"date": "2026-11-02", "kind": "post", "pillar": "Food", "idea": "x"}]}, "not in the plan")]:
        p = MarketingPlan(tenant_id=tid, period_start="2026-11-01", period_end="2026-11-30", status="pending")
        db.add(p)
        db.commit()
        with _llm(body):
            ai.run_plan(db, tid, p.id)
        assert p.status == "failed" and needle in p.error


def test_first_comment_goes_through_the_price_check(db, tid, item):
    with pytest.raises(svc.MarketingError) as exc:
        svc.add_version(db, tid, item.id, {"caption": "Monsoon mornings", "first_comment": "Weekends from Rs 15,000 per night!"},
                        origin="human", actor_id=None)
    assert exc.value.code == "content_not_allowed"


def test_tool_schemas_use_only_what_gemini_accepts():
    """Live run 18 Oct 2026: Gemini (the fallback) answered 400 to additionalProperties / const / $ref."""
    import json
    from app.services import marketing_prompts as m
    tools = [m.AUDIT_TOOL, m.PLAN_TOOL, *(m.content_tool(k) for k in ("post", "carousel", "story", "promo"))]
    for t in tools:
        s = json.dumps(t["input_schema"])
        for banned in ('"$ref"', '"$defs"', '"additionalProperties"', '"const"', '"default"', '"type": "null"'):
            assert banned not in s, (t["name"], banned)
    sticker = m.content_tool("story")["input_schema"]["properties"]["frames"]["items"]["properties"]["sticker"]
    assert sticker["nullable"] is True and sticker["properties"]["type"]["enum"] == ["poll", "question", "link"]


def test_plan_out_of_scope_may_name_banned_words(db, tid):
    tenant = db.get(__import__("app.models.tenant", fromlist=["Tenant"]).Tenant, tid)
    tenant.brand_config = {"business_profile": {"avoid": ["cheap"]}}
    db.commit()
    p = MarketingPlan(tenant_id=tid, period_start="2026-11-01", period_end="2026-11-30", status="pending")
    db.add(p)
    db.commit()
    with _llm({"goals": ["g"], "audience": "a", "pillars": ["Routes"], "cadence": "c", "out_of_scope": ["Cheap deal posts"]}):
        ai.run_plan(db, tid, p.id)
    assert p.status == "ready"


def test_plan_shape_repairs_from_a_live_run():
    fixed = ai.normalise_plan({"rotation": {"Routes": "2/week", "Life": "1/week"},
                               "calendar": [{"date": "2026-11-02", "kind": "Reel", "pillar": "Routes", "idea": "Ghat drive"},
                                            {"date": "2026-11-03", "kind": "carousel_album", "pillar": "Routes", "idea": "x"},
                                            {"date": "2026-11-04", "kind": "billboard", "pillar": "Routes", "idea": "y"}]})
    assert fixed["rotation"] == "Routes: 2/week; Life: 1/week"
    assert [e["kind"] for e in fixed["calendar"]] == ["post", "carousel", "billboard"]   # unknown kinds still fail validation
    assert fixed["calendar"][0]["idea"] == "Reel idea: Ghat drive"


def test_price_check_does_not_join_fields_or_read_dates(db, tid):
    body = {"cadence": "3 posts per day", "calendar": [{"date": "2026-10-19", "kind": "post", "pillar": "Routes", "idea": "x"}]}
    assert svc.check_text(db, tid, body) == []
    assert svc.check_text(db, tid, {"caption": "Only Rs 9,999 per night"}) != []
