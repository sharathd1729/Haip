"""Agency M2 (21 Oct 2026): photo tags + people consent, approved claims, demand calendar, brand voice draft."""
import io
import uuid
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from PIL import Image

from app.adapters import vision as vision_adapter
from app.models.audit_event import AuditEvent
from app.models.marketing import MarketingContent, MarketingPlan
from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import marketing_ai_service as ai
from app.services import marketing_brand_dna as dna
from app.services import marketing_content_service as svc
from app.services import marketing_demand as demand
from app.services import marketing_photos as photos
from app.services import marketing_review_service as review
from app.services import marketing_vision as vision
from tests.test_marketing_studio_content import BASE, make_user, ws  # noqa: F401  (fixture)


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (2000, 1500), (20, 90, 160)).save(out, format="JPEG")
    return out.getvalue()


def _asset(db, tid, alt=None):
    a = MediaAsset(id=str(uuid.uuid4()), tenant_id=tid, storage_key=f"{tid}/marketing/{uuid.uuid4().hex}.jpg",
                   mime_type="image/jpeg", bytes=10, sha256=uuid.uuid4().hex * 2, status="active", alt_text=alt)
    db.add(a)
    db.commit()
    return a


def _tags(**over):
    base = {"subjects": ["pool", "view"], "light": "golden_hour", "season": "any", "people": False,
            "text_or_logo": False, "quality": 4, "mood": ["Calm"], "description": "An infinity pool at sunset"}
    return {**base, **over}


def _tag(db, tenant, asset, answer):
    seen = {}

    def describe(model, jpeg, prompt):
        seen["size"] = Image.open(io.BytesIO(jpeg)).size
        return answer, {"input_tokens": 300, "output_tokens": 60, "est_cost_usd": 0.0002, "secs": 1.0}
    out = vision.tag_asset(db, tenant, asset.id, read_bytes=lambda k: _jpeg(), describe=describe)
    db.commit()
    return out, seen


# ── Photo tags ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_tagging_stores_tags_fills_alt_text_and_sends_a_small_photo(db, ws):  # noqa: F811
    a = _asset(db, ws["tenant"].id)
    out, seen = _tag(db, ws["tenant"], a, _tags(extra="ignored"))
    assert max(seen["size"]) <= vision.MAX_SIDE
    assert out.tags["subjects"] == ["pool", "view"] and out.tags["mood"] == ["calm"] and out.tag_model == "gemini-3.6-flash"
    assert out.alt_text == "An infinity pool at sunset" and out.tagged_at is not None
    b = _asset(db, ws["tenant"].id, alt="Owner's own words")
    assert _tag(db, ws["tenant"], b, _tags())[0].alt_text == "Owner's own words"       # never overwritten


def test_bad_model_answer_is_a_permanent_error(db, ws):  # noqa: F811
    a = _asset(db, ws["tenant"].id)
    with pytest.raises(vision_adapter.VisionError) as exc:
        _tag(db, ws["tenant"], a, {"subjects": ["spaceship"], "description": "x"})
    assert exc.value.transient is False


def test_people_photos_are_never_picked_until_the_owner_confirms_consent(client, db, ws):  # noqa: F811
    tid = ws["tenant"].id
    a = _asset(db, tid)
    _tag(db, ws["tenant"], a, _tags(people=True, subjects=["pool"]))
    assert "people" in a.tags["subjects"] and photos.library(db, tid) == []
    assert client.post(f"{BASE}/media/{a.id}/people-ok", json={"ok": True}, headers=ws["mkt_h"]).status_code == 403
    r = client.post(f"{BASE}/media/{a.id}/people-ok", json={"ok": True}, headers=ws["manager_h"])
    assert r.status_code == 200 and r.json()["people_ok"] is True
    assert [x.id for x in photos.library(db, tid)] == [a.id]
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="media.people_consent").count() == 1


def test_picker_matches_on_tags_when_the_description_is_poor(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    pool = _asset(db, tid, alt="IMG_0412")
    bed = _asset(db, tid, alt="IMG_0413")
    _tag(db, ws["tenant"], pool, _tags())
    _tag(db, ws["tenant"], bed, _tags(subjects=["bedroom"], description="A made bed", mood=["cosy"]))
    pool.alt_text, bed.alt_text = "IMG_0412", "IMG_0413"
    db.commit()
    item = svc.create_item(db, tid, kind="post", title="Evenings", actor_id=ws["mkt"].id,
                           payload={"caption": "x", "media": {"alt_text": "the pool at golden hour"}})
    db.commit()
    photos.attach_photos(db, ws["tenant"], item.id)
    v = svc.get_version(db, tid, db.get(MarketingContent, item.id).current_version_id)
    assert v.payload["media"]["asset_id"] == pool.id


def test_vision_settings_owner_only_and_blocked_models_refused(client, db, ws):  # noqa: F811
    r = client.get(f"{BASE}/vision", headers=ws["mkt_h"])
    assert r.status_code == 200 and r.json()["model"] == vision_adapter.DEFAULT_MODEL
    assert client.put(f"{BASE}/vision", json={"model": "gemini-3.6-flash"}, headers=ws["manager_h"]).status_code == 403
    r = client.put(f"{BASE}/vision", json={"model": "nvidia-vlm"}, headers=ws["owner_h"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "vision_model_unavailable"
    assert client.put(f"{BASE}/vision", json={"model": "gemini-3.6-flash"}, headers=ws["owner_h"]).status_code == 200


def test_upload_queues_tagging_and_tag_endpoints_are_tenant_scoped(client, db, ws, monkeypatch):  # noqa: F811
    queued = []
    monkeypatch.setattr("app.workers.tasks.marketing_studio.tag_photo.delay", lambda *a: queued.append(a))
    monkeypatch.setattr("app.services.media_storage.upload_marketing_media", lambda t, c, m, e: f"{t}/marketing/x.{e}")
    r = client.post(f"{BASE}/media", files={"file": ("p.jpg", _jpeg(), "image/jpeg")}, headers=ws["mkt_h"])
    assert r.status_code == 201 and queued == [(ws["tenant"].id, r.json()["id"])]
    assert client.post(f"{BASE}/media/tag-all", headers=ws["mkt_h"]).json()["queued"] == 1
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    theirs = _asset(db, other.id)
    assert client.post(f"{BASE}/media/{theirs.id}/tag", headers=ws["mkt_h"]).status_code == 404
    assert client.post(f"{BASE}/media/{theirs.id}/people-ok", json={"ok": True}, headers=ws["owner_h"]).status_code == 404
    with pytest.raises(svc.MarketingError):
        vision.tag_asset(db, ws["tenant"], theirs.id, read_bytes=lambda k: _jpeg(), describe=lambda *a: ({}, {}))


# ── Approved claims ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_an_approved_claim_makes_its_number_usable(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    item = svc.create_item(db, tid, kind="post", title="x", actor_id=None, payload={"caption": "Only 12 km from Madikeri."})
    db.commit()
    assert "unverified_number" in {f["rule"] for f in review.current(db, ws["tenant"], item).findings}
    ai.put_profile(db, ws["tenant"], {"claims": [{"text": "12 km from Madikeri town", "source": "Google Maps"}]}, ws["owner"].id)
    db.commit()
    assert "unverified_number" not in {f["rule"] for f in review.current(db, ws["tenant"], item).findings}


# ── Demand ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_long_weekends_include_bridges_and_occasions_have_kinds():
    lws = demand.long_weekends("KA", date(2026, 10, 1), date(2027, 1, 31))
    assert {"start": "2026-10-02", "end": "2026-10-04", "days": 3, "leave_days": 0,
            "reason": "Mahatma Gandhi's Jayanti"} in lws                           # Friday holiday
    dussehra = next(x for x in lws if x["start"] == "2026-10-17")
    assert dussehra["days"] == 4 and dussehra["leave_days"] == 1 and "Monday" in dussehra["reason"]
    occ = demand.occasions("KA", date(2026, 11, 1), date(2026, 12, 31))
    assert any(o["name"].startswith("Christmas") and o["kind"] == "public" for o in occ)
    assert demand.state_code("Karnataka") == "KA" and demand.state_code("Atlantis") is None


def test_gaps_are_sellable_windows_with_every_free_vehicle_occasions_first():
    today = date(2026, 9, 25)
    end = date(2026, 10, 31)
    lws = demand.long_weekends("KA", today, end)
    occ = demand.occasions("KA", today, end)
    all_nights = [today + timedelta(days=i) for i in range(40)]
    free = {"Ratha 1": all_nights, "Ratha 2": [n for n in all_nights if n != date(2026, 10, 3)]}
    got = demand.gaps(free, lws, occ, today=today, end=end)
    gandhi = next(g for g in got if g["start"] == "2026-10-02")
    assert gandhi["end"] == "2026-10-04" and gandhi["nights"] == 2 and gandhi["properties"] == ["Ratha 1"]
    assert "long weekend" in gandhi["why"][0] and "Gandhi" in gandhi["why"][0]
    weekend = next(g for g in got if g["start"] == "2026-10-09")
    assert weekend["why"] == ["weekend"] and weekend["properties"] == ["Ratha 1", "Ratha 2"] and weekend["nights"] == 2
    kinds = [g["why"] == ["weekend"] for g in got]
    assert kinds == sorted(kinds)                                                # occasions before plain weekends
    assert all(g["nights"] <= 4 for g in got)                                    # windows, never a 54-night run
    assert demand.gaps({"Ratha 1": []}, lws, occ, today=today, end=end) == []
    karwa = [g for g in got if g["why"] == ["Karaka Chaturthi (Karwa Chouth)"]]
    assert karwa == []                                                           # an optional festival alone is no window


def test_free_nights_use_the_booking_availability_check(db, ws):  # noqa: F811
    from app.models.property import Property
    tid = ws["tenant"].id
    db.add(Property(tenant_id=tid, name="Ratha 1", slug=f"r1-{uuid.uuid4().hex[:6]}", type="caravan", is_active=True))
    db.commit()
    start = date(2026, 11, 1)
    with patch("app.services.calculator_service.calculator_service.is_open",
               side_effect=lambda db_, t, p, a, b: a != "2026-11-02"):
        free = demand.free_nights(db, tid, start, start + timedelta(days=4))
    assert free == {"Ratha 1": [date(2026, 11, 1), date(2026, 11, 3), date(2026, 11, 4)]}


def test_plan_gets_the_demand_brief_and_keeps_it(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    plan = MarketingPlan(tenant_id=tid, period_start="2026-11-10", period_end="2026-11-16", status="pending")
    db.add(plan)
    db.commit()
    brief = {"gaps": [{"property": "Ratha 1", "start": "2026-11-13", "end": "2026-11-16", "nights": 3, "why": ["weekend"]}]}
    seen = {}

    def fake(task, tenant_id, system, user, tool):
        seen["user"], seen["system"] = user, system
        return {"goals": ["Fill 13-16 Nov"], "audience": "Couples", "pillars": ["Routes"], "cadence": "3",
                "campaigns": [{"name": "Mid-Nov weekend", "goal": "Fill Ratha 1", "targets": "2026-11-13 to 2026-11-16"}],
                "reactive_days": ["2026-11-12"],
                "calendar": [{"date": "2026-11-10", "kind": "post", "pillar": "Routes", "idea": "Coorg loop",
                              "targets": "2026-11-13 to 2026-11-16", "campaign": "Mid-Nov weekend", "bucket": "proven",
                              "indicator": "DMs about 13 Nov", "stop_if": "No DMs in 3 days"}]}, {"model": "m"}, "nvidia"
    with patch.object(ai, "_demand", return_value=brief), patch.object(ai, "_call", side_effect=fake):
        ai.run_plan(db, tid, plan.id)
    assert plan.status == "ready", plan.error
    assert "2026-11-13" in seen["user"] and "Demand comes first" in seen["system"] and plan.prompt_version == "marketing-plan-v6"
    assert plan.body["demand"] == brief and plan.body["calendar"][0]["bucket"] == "proven"


def test_demand_endpoint_read_capability(client, db, ws):  # noqa: F811
    r = client.get(f"{BASE}/demand", headers=ws["mkt_h"])
    assert r.status_code == 200 and {"occasions", "long_weekends", "gaps"} <= set(r.json())
    _, foh_h = make_user(db, ws["tenant"].id, UserRole.FOH)
    assert client.get(f"{BASE}/demand", headers=foh_h).status_code == 403


# ── Brand voice draft ───────────────────────────────────────────────────────────────────────────────────────────────

def test_brand_draft_is_a_suggestion_from_published_text_only(db, ws):  # noqa: F811
    from app.models.property import Property
    tid = ws["tenant"].id
    out = dna.run(db, tid)
    assert out["status"] == "failed" and "Nothing published" in out["error"]
    db.add(Property(tenant_id=tid, name="Ratha 1", slug=f"r1-{uuid.uuid4().hex[:6]}", type="caravan", is_active=True,
                    description="A chauffeur-driven luxury caravan for slow trips through Coorg."))
    db.commit()
    seen = {}

    def fake(task, tenant_id, system, user, tool):
        seen.update(task=task, user=user)
        return {"tone": "Unhurried", "voice": [{"trait": "Slow", "we_are": "Unhurried", "we_are_not": "Rushed"}],
                "claims": [{"text": "chauffeur-driven", "source": "property description"}], "gaps": ["Who are your guests?"]}, \
            {"model": "m"}, "nvidia"
    before = ai.get_profile(ws["tenant"])
    with patch.object(ai, "_call", side_effect=fake):
        out = dna.run(db, tid)
    db.commit()
    assert seen["task"] == "marketing_brand_dna" and "slow trips through Coorg" in seen["user"]
    assert out["status"] == "ready" and out["draft"]["voice"][0]["we_are_not"] == "Rushed"
    assert ai.get_profile(ws["tenant"]) == before                                # nothing applied to the profile


def test_brand_draft_endpoints_queue_once_and_need_edit(client, db, ws, monkeypatch):  # noqa: F811
    queued = []
    monkeypatch.setattr("app.workers.tasks.marketing_studio.draft_profile.delay", lambda *a: queued.append(a))
    _, foh_h = make_user(db, ws["tenant"].id, UserRole.FOH)
    assert client.post(f"{BASE}/profile/draft", headers=foh_h).status_code == 403
    r = client.post(f"{BASE}/profile/draft", headers=ws["mkt_h"])
    assert r.status_code == 202 and r.json()["status"] == "pending" and queued == [(ws["tenant"].id,)]
    assert client.post(f"{BASE}/profile/draft", headers=ws["mkt_h"]).status_code == 409
    assert client.get(f"{BASE}/profile/draft", headers=ws["mkt_h"]).json()["status"] == "pending"
