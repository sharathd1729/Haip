"""Agency M0 (21 Oct 2026): photo picker, rendered previews, copywriter context, per-step runs, pause, stuck runs."""
import io
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from app.models.marketing import MarketingContent, MarketingTask
from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.services import marketing_agency_run as runs
from app.services import marketing_agency_service as agency
from app.services import marketing_ai_service as ai
from app.services import marketing_content_service as svc
from app.services import marketing_context
from app.services import marketing_photos as photos
from app.services import marketing_render as render
from tests.test_marketing_agency import _fake_call, _seed_insights
from tests.test_marketing_studio_content import BASE, ws  # noqa: F401  (fixture)


def _jpeg(colour=(30, 110, 80)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (1400, 1000), colour).save(out, format="JPEG")
    return out.getvalue()


PHOTO = _jpeg()


def _photo(db, tenant_id, alt, *, mime="image/jpeg", status="active", property_id=None):
    a = MediaAsset(id=str(uuid.uuid4()), tenant_id=tenant_id, storage_key=f"{tenant_id}/marketing/{uuid.uuid4().hex}.jpg",
                   mime_type=mime, bytes=10, sha256=uuid.uuid4().hex * 2, status=status, alt_text=alt,
                   property_id=property_id)
    db.add(a)
    db.commit()
    return a


@pytest.fixture(autouse=True)
def _storage(monkeypatch):
    monkeypatch.setattr("app.services.media_storage.upload_marketing_media",
                        lambda t, c, m, e: f"{t}/marketing/{uuid.uuid4().hex}.{e}")
    monkeypatch.setattr("app.services.media_library_service._read_object", lambda key: PHOTO)


def _other_tenant(db):
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    return other


# ── Photo picker ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_picker_matches_the_described_photo_and_avoids_repeats(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    pool = _photo(db, tid, "Infinity pool at sunset")
    chai = _photo(db, tid, "Morning chai on the caravan deck")
    _photo(db, tid, "Bedroom with linen")
    _photo(db, tid, "AI draft", status="pending_review")                    # not approved: never picked
    _photo(db, tid, "Rendered", status="derived")                           # a posted render: never a source
    item = svc.create_item(db, tid, kind="carousel", title="Life on board: mornings", actor_id=ws["mkt"].id, payload={
        "caption": "Mornings.", "slides": [{"headline": "Chai first", "media": {"alt_text": "chai on the deck"}},
                                          {"headline": "Then the pool", "media": {"alt_text": "the pool"}}]})
    db.commit()
    assert photos.attach_photos(db, ws["tenant"], item.id, actor_id=None) == 2
    db.commit()
    v = svc.get_version(db, tid, db.get(MarketingContent, item.id).current_version_id)
    chosen = [s["media"]["asset_id"] for s in v.payload["slides"]]
    assert chosen == [chai.id, pool.id] and v.origin == "ai" and "Photos chosen" in v.note
    assert v.payload["design"] == {"style": "overlay", "colour": "#1E7A5A", "accent": None, "font": "plain",
                                   "logo_asset_id": None, "logo_position": "none"}   # brand kit frozen in (M3)
    assert photos.attach_photos(db, ws["tenant"], item.id) == 0              # nothing left to fill: no new version


def test_picker_never_uses_another_tenants_photos(db, ws):  # noqa: F811
    other = _other_tenant(db)
    _photo(db, other.id, "Infinity pool at sunset")
    item = svc.create_item(db, ws["tenant"].id, kind="post", title="Pool", actor_id=ws["mkt"].id,
                           payload={"caption": "Pool.", "media": {"alt_text": "infinity pool"}})
    db.commit()
    assert photos.library(db, ws["tenant"].id) == []
    photos.attach_photos(db, ws["tenant"], item.id)
    v = svc.get_version(db, ws["tenant"].id, db.get(MarketingContent, item.id).current_version_id)
    assert (v.payload.get("media") or {}).get("asset_id") is None


def test_recently_used_photo_loses_to_an_unused_equal_match(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    a = _photo(db, tid, "caravan on the ghat road")
    b = _photo(db, tid, "caravan on the ghat road at dawn")
    svc.create_item(db, tid, kind="post", title="Old", actor_id=ws["mkt"].id,
                    payload={"caption": "Old.", "media": {"asset_id": b.id}})
    db.commit()
    used = photos.recent_use(db, tid)
    assert used[b.id] == 1
    assert photos.pick([a, b], {"caravan", "ghat", "road"}, property_id=None, used=used, taken=set()).id == a.id


def test_the_slots_photo_description_outweighs_the_slide_text(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    pool = _photo(db, tid, "Infinity pool at sunset")
    dining = _photo(db, tid, "Dining table set for breakfast")                # newer: wins ties
    item = svc.create_item(db, tid, kind="story", title="Mornings", actor_id=ws["mkt"].id, payload={
        "frames": [{"text": "Coffee by the pool or breakfast inside?", "media": {"alt_text": "pool"}}]})
    db.commit()
    photos.attach_photos(db, ws["tenant"], item.id)
    v = svc.get_version(db, tid, db.get(MarketingContent, item.id).current_version_id)
    assert v.payload["frames"][0]["media"]["asset_id"] == pool.id != dining.id


def test_a_photo_with_nothing_in_common_is_used_but_named_in_the_note(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    _photo(db, tid, "Bathroom with a stone basin")
    item = svc.create_item(db, tid, kind="carousel", title="Chauffeur", actor_id=ws["mkt"].id, payload={
        "caption": "x", "slides": [{"headline": "Stone basin", "media": {"alt_text": "bathroom"}},
                                   {"headline": "Chauffeur driven", "media": {"alt_text": "driver at the wheel"}}]})
    db.commit()
    assert photos.attach_photos(db, ws["tenant"], item.id) == 2
    v = svc.get_version(db, tid, db.get(MarketingContent, item.id).current_version_id)
    assert v.note.endswith("no close match for slide 2 - check or add a better photo")


def test_pick_photos_api_needs_edit_and_refuses_items_in_review(client, db, ws):  # noqa: F811
    tid = ws["tenant"].id
    _photo(db, tid, "pool")
    item = svc.create_item(db, tid, kind="post", title="Pool", actor_id=ws["mkt"].id, payload={"caption": "x"})
    db.commit()
    from app.models.user import UserRole
    from tests.test_marketing_studio_content import make_user
    _, foh_h = make_user(db, tid, UserRole.FOH)
    assert client.post(f"{BASE}/content/{item.id}/pick-photos", headers=foh_h).status_code == 403
    r = client.post(f"{BASE}/content/{item.id}/pick-photos", headers=ws["mkt_h"])
    assert r.status_code == 200 and r.json()["filled"] == 1
    svc.submit(db, tid, item.id, r.json()["version_id"], ws["mkt"])
    db.commit()
    r = client.post(f"{BASE}/content/{item.id}/pick-photos", headers=ws["mkt_h"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_editable"


# ── Rendered preview ────────────────────────────────────────────────────────────────────────────────────────────────

def test_preview_shows_the_rendered_images_without_storing_anything(client, db, ws):  # noqa: F811
    tid = ws["tenant"].id
    png = _photo(db, tid, "deck", mime="image/png")
    item = svc.create_item(db, tid, kind="story", title="Story", actor_id=ws["mkt"].id, payload={
        "frames": [{"text": "Two roads", "cta": "Reply", "media": {"asset_id": png.id}}], "design": {"style": "panel"}})
    db.commit()
    before = db.query(MediaAsset).filter_by(tenant_id=tid).count()
    r = client.get(f"{BASE}/content/{item.id}/preview", headers=ws["mkt_h"])
    body = r.json()
    assert r.status_code == 200 and body["problems"] == [] and len(body["frames"]) == 1
    assert body["frames"][0]["src"].startswith("data:image/jpeg;base64,") and body["frames"][0]["style"] == "panel"
    assert db.query(MediaAsset).filter_by(tenant_id=tid).count() == before
    import base64
    img = Image.open(io.BytesIO(base64.b64decode(body["frames"][0]["src"].split(",", 1)[1])))
    assert img.size == (540, 960)                                            # half of 1080x1920


def test_preview_explains_a_missing_photo_and_is_tenant_scoped(client, db, ws):  # noqa: F811
    item = svc.create_item(db, ws["tenant"].id, kind="post", title="No photo", actor_id=ws["mkt"].id,
                           payload={"caption": "x"})
    db.commit()
    body = client.get(f"{BASE}/content/{item.id}/preview", headers=ws["mkt_h"]).json()
    assert body["frames"] == [] and "photo" in body["problems"][0]
    other = _other_tenant(db)
    theirs = svc.create_item(db, other.id, kind="post", title="Theirs", actor_id=None, payload={"caption": "x"})
    db.commit()
    assert client.get(f"{BASE}/content/{theirs.id}/preview", headers=ws["mkt_h"]).status_code == 404


def test_render_refuses_another_tenants_photo(db, ws):  # noqa: F811
    other = _other_tenant(db)
    theirs = _photo(db, other.id, "pool")
    with pytest.raises(render.MediaError) as exc:
        render.images(db, ws["tenant"], "post", {"media": {"asset_id": theirs.id}, "overlay_text": "Hi"})
    assert exc.value.code == "photo_unavailable"


def test_typographic_punctuation_is_drawn_as_plain_text():
    assert render._drawable("Chauffeur\u2011Driven \u2014 Caf\u00e9 \u20b9") == "Chauffeur-Driven - Cafe Rs"


# ── Copywriter context ──────────────────────────────────────────────────────────────────────────────────────────────

def test_copywriter_sees_plan_siblings_history_notes_and_photo_descriptions(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    river = _photo(db, tid, "Caravan parked by the Kabini river")
    old = svc.create_item(db, tid, kind="post", title="Old", actor_id=ws["mkt"].id,
                          payload={"caption": "Wake up to the river.\nMore lines.", "media": {"asset_id": river.id}})
    db.commit()
    svc.submit(db, tid, old.id, old.current_version_id, ws["mkt"])
    svc.reject(db, tid, old.id, old.current_version_id, ws["owner"], "Less about the bed, more about the view")
    from app.models.marketing import MarketingPlan
    plan = MarketingPlan(tenant_id=tid, period_start="2026-10-22", period_end="2026-10-28", status="ready", body={
        "goals": ["More DMs"], "audience": "Couples from Bengaluru", "position": "Slow road trips", "pillars": ["Routes"],
        "out_of_scope": ["cheap deals"], "cadence": "3",
        "calendar": [{"date": "2026-10-22", "kind": "post", "pillar": "Routes", "idea": "Kabini loop"},
                     {"date": "2026-10-23", "kind": "story", "pillar": "Routes", "idea": "Ghat poll"}]})
    db.add(plan)
    db.commit()
    item = svc.create_item(db, tid, kind="post", title="Routes: Kabini loop", actor_id=None, plan_id=plan.id,
                           planned_for="2026-10-22")
    db.commit()
    text = marketing_context.build(db, tid, item)
    assert "Couples from Bengaluru" in text and "'pillar': 'Routes', 'idea': 'Kabini loop'" in text
    assert "Ghat poll" in text and "Wake up to the river." in text and "More lines" not in text
    assert "Less about the bed" in text and "Caravan parked by the Kabini river" in text

    seen = {}

    def fake(task, tenant_id, system, user, tool):
        seen["user"], seen["system"] = user, system
        return {"caption": "Kabini, slowly.", "design": {"style": "panel", "colour": "#FF0000"}}, {"model": "m"}, "nvidia"
    with patch.object(ai, "_call", side_effect=fake):
        ai.run_content(db, tid, item.id, None, "Kabini loop")
    v = svc.get_version(db, tid, item.current_version_id)
    assert "Less about the bed" in seen["user"] and "designer picks a library photo" in seen["system"]
    assert {k: v.payload["design"][k] for k in ("style", "colour")} == {"style": "panel", "colour": None} and v.prompt_version == "marketing-content-v8"


def test_context_notes_on_this_post_come_first_and_other_tenants_never_leak(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    mine = _photo(db, tid, "Our deck")
    item = svc.create_item(db, tid, kind="post", title="Mine", actor_id=ws["mkt"].id,
                           payload={"caption": "Mine.", "media": {"asset_id": mine.id}})
    db.commit()
    svc.submit(db, tid, item.id, item.current_version_id, ws["mkt"])
    svc.reject(db, tid, item.id, item.current_version_id, ws["owner"], "Shorter first line")
    other = _other_tenant(db)
    _photo(db, other.id, "Their secret villa")
    theirs = svc.create_item(db, other.id, kind="post", title="Theirs", actor_id=None, payload={"caption": "Their caption."})
    db.commit()
    text = marketing_context.build(db, tid, item)
    assert "THIS post" in text and "Shorter first line" in text
    assert "Their secret villa" not in text and "Their caption" not in text and theirs.id not in text


# ── Per-step runs, pause, stuck runs ────────────────────────────────────────────────────────────────────────────────

def _start(db, ws, trigger="manual"):  # noqa: F811
    _seed_insights(db, ws["tenant"].id)
    return runs.start_run(db, ws["tenant"].id, trigger=trigger, actor_id=ws["owner"].id)


def test_each_unit_is_one_call_and_drafts_go_one_at_a_time(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    _photo(db, tid, "Coorg coffee estate road")
    start = datetime.now(ZoneInfo("Asia/Kolkata")).date() + timedelta(days=1)
    run = _start(db, ws)
    seen = []
    with patch.object(ai, "_call", side_effect=_fake_call(start)), patch.object(agency, "notify_needs_approval"):
        while runs.run_step(db, tid, run.run_id):
            seen.append((db.query(MarketingTask).filter_by(id=run.id).one().detail or {}).get("state", {}).get("next"))
    assert seen == ["competitors", "plan", "draft", "draft", "draft", "photos", "image", "submit"]
    db.refresh(run)
    assert run.status == "done" and run.detail["drafts"] == 3
    draft = db.query(MarketingTask).filter_by(run_id=run.run_id, step="draft").one()
    assert draft.status == "done" and draft.detail == {"drafted": 3, "failed": 0, "rewritten": 0}
    photos_step = db.query(MarketingTask).filter_by(run_id=run.run_id, step="photos").one()
    assert photos_step.status == "done" and photos_step.detail["slots_filled"] >= 3
    items = db.query(MarketingContent).filter_by(tenant_id=tid).all()
    assert {i.status for i in items} == {"in_review"}
    for i in items:                                                    # every slot has a library photo and a colour
        v = svc.get_version(db, tid, i.current_version_id)
        assert all(f["asset_id"] for f in render.frames(i.kind, v.payload)) and v.payload["design"]["colour"]


def test_one_draft_failing_does_not_stop_the_others(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    start = datetime.now(ZoneInfo("Asia/Kolkata")).date() + timedelta(days=1)
    good = _fake_call(start)

    def flaky(task, tenant_id, system, user, tool):
        if task == "marketing_content" and "Kind: carousel" in user:
            raise ai.LLMTransientError("504")
        return good(task, tenant_id, system, user, tool)
    _seed_insights(db, tid)
    with patch.object(ai, "_call", side_effect=flaky), patch.object(agency, "notify_needs_approval"):
        run_id = runs.run_week(db, tid, trigger="manual")
    draft = db.query(MarketingTask).filter_by(run_id=run_id, step="draft").one()
    assert draft.status == "done" and draft.detail == {"drafted": 2, "failed": 1, "rewritten": 0}
    failed = db.query(MarketingContent).filter_by(tenant_id=tid, kind="carousel").one()
    assert failed.generation_status == "failed" and "unavailable" in failed.generation_error


def test_pause_stops_a_manual_run_at_its_next_unit(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    run = _start(db, ws)
    with patch.object(ai, "_call", side_effect=_fake_call(datetime.now().date())) as call:
        assert runs.run_step(db, tid, run.run_id) is True                  # audit done
        agency.update_agency(db, ws["tenant"], ws["owner"].id, paused=True)
        db.commit()
        assert runs.run_step(db, tid, run.run_id) is False
    assert call.call_count == 1
    db.refresh(run)
    assert run.status == "failed" and "paused" in run.error
    assert runs.start_run(db, tid, trigger="manual").status == "skipped"   # a new run does nothing while paused


def test_stuck_run_is_closed_and_the_next_one_can_start(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    run = _start(db, ws)
    open_step = MarketingTask(tenant_id=tid, run_id=run.run_id, role="copy", step="draft", status="running",
                              trigger="manual")
    db.add(open_step)
    db.commit()
    assert runs.running(db, tid) is not None
    assert runs.sweep_stuck(db, now=datetime.now(timezone.utc) + runs.STUCK_AFTER + timedelta(minutes=1)) == 1
    db.refresh(run)
    db.refresh(open_step)
    assert run.status == "failed" and "no progress" in run.error and open_step.status == "failed"
    assert runs.running(db, tid) is None and runs.run_step(db, tid, run.run_id) is False


def test_celery_step_chain_queues_the_next_unit(db, ws, monkeypatch):  # noqa: F811
    from app.workers.tasks import marketing_studio as tasks
    queued = []
    monkeypatch.setattr(tasks.agency_step, "delay", lambda *a: queued.append(a))
    monkeypatch.setattr(tasks, "SessionLocal", lambda: _Ctx(db))
    run_id = tasks.agency_run_week(ws["tenant"].id, "manual", ws["owner"].id)
    assert queued == [(ws["tenant"].id, run_id)]
    with patch.object(ai, "_call", side_effect=ai.LLMTransientError("504")):
        assert tasks.agency_step(ws["tenant"].id, run_id) == {"more": True}
    assert queued[-1] == (ws["tenant"].id, run_id) and len(queued) == 2


class _Ctx:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *a):
        return False
