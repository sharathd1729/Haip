"""Agency M3 (21 Oct 2026): premium writer + fallback, hook options, critic scores + one rewrite, brand kit, look variants."""
import io
import uuid
from unittest.mock import patch

import pytest
from PIL import Image

from app.models.audit_event import AuditEvent
from app.models.marketing import MarketingContent, MarketingTask
from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import marketing_agency_run as runs
from app.services import marketing_agency_service as agency
from app.services import marketing_ai_service as ai
from app.services import marketing_brand_kit as kit_svc
from app.services import marketing_content_service as svc
from app.services import marketing_photos as photos
from app.services import marketing_render as render
from app.services import marketing_review_service as review
from tests.test_marketing_review import _run_with
from tests.test_marketing_studio_content import BASE, make_user, ws  # noqa: F401  (fixture)

GOOD = "Monsoon in Coorg, from the caravan's deck: mist on the coffee estate at 7am. DM us for dates."


def _jpeg(colour=(30, 110, 80), size=(1400, 1000)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, format="JPEG")
    return out.getvalue()


def _png_logo() -> bytes:
    out = io.BytesIO()
    img = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    img.paste((250, 200, 40, 255), (50, 50, 350, 150))
    img.save(out, format="PNG")
    return out.getvalue()


PHOTO, LOGO = _jpeg(), _png_logo()


def _asset(db, tid, alt="deck at dawn", mime="image/jpeg"):
    a = MediaAsset(id=str(uuid.uuid4()), tenant_id=tid, storage_key=f"{tid}/marketing/{uuid.uuid4().hex}",
                   mime_type=mime, bytes=10, sha256=uuid.uuid4().hex * 2, status="active", alt_text=alt)
    db.add(a)
    db.commit()
    return a


@pytest.fixture(autouse=True)
def _storage(monkeypatch):
    logos = set()
    monkeypatch.setattr("app.services.media_storage.upload_marketing_media",
                        lambda t, c, m, e: f"{t}/marketing/{uuid.uuid4().hex}.{e}")
    monkeypatch.setattr("app.services.media_library_service._read_object",
                        lambda key: LOGO if key in logos else PHOTO)
    return logos


# ── Premium writer ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_premium_writer_is_used_when_set_and_falls_back_to_standard(db, ws):  # noqa: F811
    tenant = ws["tenant"]
    item = svc.create_item(db, tenant.id, kind="post", title="Deck", actor_id=None, payload={"caption": "x"})
    db.commit()
    assert ai.creative_model(tenant) == "standard"
    ai.set_creative_model(db, tenant, "premium", ws["owner"].id)
    db.commit()
    tasks = []

    def flaky(task, tenant_id, system, user, tool):
        tasks.append(task)
        if task == "marketing_content_premium":
            raise ai.LLMTransientError("Gemini 503")
        assert "hook_options" in tool["input_schema"]["properties"]
        return {"caption": GOOD, "hook_options": ["Mist at 7am.", "The deck at dawn.", "extra"]}, {"model": "m"}, "nvidia"
    with patch.object(ai, "_call", side_effect=flaky):
        ai.run_content(db, tenant.id, item.id, None, "deck at dawn")
    v = svc.get_version(db, tenant.id, item.current_version_id)
    assert tasks == ["marketing_content_premium", "marketing_content"]          # a draft is never lost to Gemini
    assert "hook_options" not in v.payload and v.payload["caption"] == GOOD
    assert "Other first lines: Mist at 7am. | The deck at dawn." in v.note and "extra" not in v.note
    assert db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="marketing.creative_model.updated").count() == 1


def test_creative_model_endpoint_is_owner_only_and_validated(client, db, ws):  # noqa: F811
    assert client.get(f"{BASE}/creative-model", headers=ws["mkt_h"]).json() == {"model": "standard",
                                                                              "models": ["standard", "premium"]}
    assert client.put(f"{BASE}/creative-model", json={"model": "premium"}, headers=ws["mkt_h"]).status_code == 403
    assert client.put(f"{BASE}/creative-model", json={"model": "gpt-9"}, headers=ws["owner_h"]).status_code == 422
    r = client.put(f"{BASE}/creative-model", json={"model": "premium"}, headers=ws["owner_h"])
    assert r.status_code == 200 and r.json()["model"] == "premium"
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    assert ai.creative_model(other) == "standard"                                # a setting never leaks across tenants


def test_premium_route_is_gemini():
    from app.adapters.llm import _TASK_ROUTES
    assert _TASK_ROUTES["marketing_content_premium"] == ("gemini", "gemini-3.6-flash")


# ── Critic ──────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("scores,weak", [
    ({"hook": 4, "specificity": 4, "voice": 4, "clarity": 3, "ask": 4}, []),
    ({"hook": 2, "specificity": 4, "voice": 5, "clarity": 5, "ask": 5}, ["hook"]),              # one mark at the floor
    ({"hook": 3, "specificity": 3, "voice": 3, "clarity": 4, "ask": 3}, ["hook", "specificity", "voice", "ask"]),
    (None, []),
])
def test_weak_points_apply_the_bar(scores, weak):
    assert review.weak_points(scores) == weak


def test_scores_below_the_bar_trigger_one_rewrite_with_the_critics_notes(db, ws):  # noqa: F811
    low = {"hook": 2, "specificity": 3, "voice": 4, "clarity": 4, "ask": 3}
    high = {"hook": 4, "specificity": 4, "voice": 4, "clarity": 4, "ask": 4}
    run_id, item, briefs = _run_with(db, ws, [GOOD], scores=[low, high])
    assert len(briefs) == 2 and "hook: the first line is flat" in briefs[1] and "Write it again" in briefs[1]
    assert item.status == "in_review"
    assert db.query(MarketingTask).filter_by(run_id=run_id, step="draft").one().detail["rewritten"] == 1
    row = review.current(db, ws["tenant"], item)
    assert row.scores == high and review.as_dict(row)["weak"] == []


def test_a_good_draft_is_not_rewritten(db, ws):  # noqa: F811
    _, item, briefs = _run_with(db, ws, [GOOD], scores=[{"hook": 4, "specificity": 5, "voice": 4, "clarity": 4, "ask": 4}])
    assert len(briefs) == 1 and item.status == "in_review"


def test_low_marks_get_one_rewrite_only_and_never_block_submission(db, ws):  # noqa: F811
    _, item, briefs = _run_with(db, ws, [GOOD], scores=[{"hook": 1, "specificity": 1, "voice": 1, "clarity": 1, "ask": 1}])
    assert len(briefs) == 2 and item.status == "in_review"                  # the approver sees the marks; a person decides


def test_fix_brief_puts_blockers_before_polish():
    brief = review.fix_brief("Deck", [{"where": "caption", "message": "Unknown number", "severity": "high", "quote": "40"}],
                             weak=["ask"], advice=[{"where": "caption", "message": "Formal", "severity": "medium"},
                                                   {"where": "caption", "message": "nit", "severity": "low"}])
    assert brief.index("Unknown number") < brief.index("ask: the next step") < brief.index("Formal")
    assert "nit" not in brief


# ── Brand kit ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_brand_kit_is_frozen_into_the_draft_and_the_logo_is_never_a_post_photo(db, ws, _storage):  # noqa: F811
    tenant = ws["tenant"]
    logo = _asset(db, tenant.id, alt="deck logo", mime="image/png")
    _storage.add(logo.storage_key)
    photo = _asset(db, tenant.id, alt="deck at dawn")
    kit_svc.put_kit(db, tenant, {"logo_asset_id": logo.id, "primary": "#123456", "accent": "#E0694A", "font": "sans",
                                 "logo_position": "top_left"}, ws["owner"].id)
    db.commit()
    assert [a.id for a in photos.library(db, tenant.id)] == [photo.id]
    item = svc.create_item(db, tenant.id, kind="post", title="Deck", actor_id=None,
                           payload={"caption": GOOD, "overlay_text": "Mist at 7am", "media": {"alt_text": "deck logo"}})
    db.commit()
    photos.attach_photos(db, tenant, item.id)
    db.commit()
    v = svc.get_version(db, tenant.id, item.current_version_id)
    assert v.payload["media"]["asset_id"] == photo.id
    assert v.payload["design"] == {"style": "overlay", "colour": "#123456", "accent": "#E0694A", "font": "sans",
                                   "logo_asset_id": logo.id, "logo_position": "top_left"}
    kit_svc.put_kit(db, tenant, {"primary": "#654321"}, ws["owner"].id)       # a later kit change...
    db.commit()
    assert svc.get_version(db, tenant.id, item.current_version_id).payload["design"]["colour"] == "#123456"   # ...is not applied
    # The logo lands in the top-left corner of the drawn image.
    with_logo = render.images(db, tenant, "post", v.payload)[0][0]
    plain = render.images(db, tenant, "post", {**v.payload, "design": {**v.payload["design"], "logo_position": "none"}})[0][0]
    corner = (60, 60, 200, 120)
    a = Image.open(io.BytesIO(with_logo)).crop(corner).convert("RGB").getcolors(100000)
    b = Image.open(io.BytesIO(plain)).crop(corner).convert("RGB").getcolors(100000)
    assert a != b


def test_text_hash_ignores_the_brand_kit_fields():
    from app.schemas.marketing import text_of
    base = {"caption": "x", "design": {"style": "overlay"}}
    kit = {"caption": "x", "design": {"style": "overlay", "font": "serif", "logo_position": "top_left",
                                      "logo_asset_id": "abc", "accent": "#112233"}}
    assert text_of(base) == text_of(kit)


def test_brand_kit_rejects_another_tenants_logo_and_needs_approver_role(client, db, ws):  # noqa: F811
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    theirs = _asset(db, other.id, mime="image/png")
    r = client.put(f"{BASE}/brand-kit", json={"logo_asset_id": theirs.id}, headers=ws["owner_h"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "logo_unavailable"
    assert client.put(f"{BASE}/brand-kit", json={"primary": "#123456"}, headers=ws["mkt_h"]).status_code == 403
    assert client.put(f"{BASE}/brand-kit", json={"primary": "red"}, headers=ws["owner_h"]).status_code == 422
    r = client.put(f"{BASE}/brand-kit", json={"primary": "#123456", "font": "serif"}, headers=ws["manager_h"])
    assert r.status_code == 200 and r.json()["font"] == "serif"
    assert client.get(f"{BASE}/brand-kit", headers=ws["mkt_h"]).json()["primary"] == "#123456"
    _, foh_h = make_user(db, ws["tenant"].id, UserRole.FOH)
    assert client.get(f"{BASE}/brand-kit", headers=foh_h).status_code == 403


def test_an_archived_logo_fails_the_render_instead_of_posting_without_it(db, ws):  # noqa: F811
    tenant = ws["tenant"]
    logo, photo = _asset(db, tenant.id, mime="image/png"), _asset(db, tenant.id)
    payload = {"caption": "x", "media": {"asset_id": photo.id},
               "design": {"style": "photo", "logo_asset_id": logo.id, "logo_position": "top_right"}}
    logo.status = "archived"
    db.commit()
    from app.services.media_library_service import MediaError
    with pytest.raises(MediaError) as exc:
        render.images(db, tenant, "post", payload)
    assert exc.value.code == "logo_unavailable"


def test_missing_noto_font_falls_back_to_the_bundled_one(monkeypatch):
    monkeypatch.setattr(render, "FONT_DIRS", ("/nowhere",))
    render.font_path.cache_clear()
    try:
        assert render.font_path("sans", True) is None
        assert render._drawable("Kerala — ₹1", render.font_path("sans", True) is not None) == "Kerala - Rs 1"
        data = render.draw(PHOTO, (540, 675), style="panel", colour="#123456", headline="Hi", sub=None, cta="DM us",
                           accent="#E0694A", font="sans")
        assert Image.open(io.BytesIO(data)).size == (540, 675)
    finally:
        render.font_path.cache_clear()


# ── Look variants ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_variants_draw_the_first_image_in_each_look_and_store_nothing(client, db, ws):  # noqa: F811
    tid = ws["tenant"].id
    a, b = _asset(db, tid), _asset(db, tid)
    item = svc.create_item(db, tid, kind="carousel", title="x", actor_id=None, payload={
        "caption": "Route", "design": {"style": "panel"},
        "slides": [{"headline": "Day 1", "media": {"asset_id": a.id}}, {"headline": "Day 2", "media": {"asset_id": b.id}}]})
    db.commit()
    before = db.query(MediaAsset).filter_by(tenant_id=tid).count()
    body = client.get(f"{BASE}/content/{item.id}/variants", headers=ws["mkt_h"]).json()
    assert body["current"] == "panel" and [v["style"] for v in body["variants"]] == ["overlay", "panel", "photo"]
    assert all(v["src"].startswith("data:image/jpeg;base64,") for v in body["variants"])
    assert len({v["src"] for v in body["variants"]}) == 3
    assert db.query(MediaAsset).filter_by(tenant_id=tid).count() == before

    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    theirs = svc.create_item(db, other.id, kind="post", title="t", actor_id=None, payload={"caption": "t"})
    db.commit()
    assert client.get(f"{BASE}/content/{theirs.id}/variants", headers=ws["mkt_h"]).status_code == 404
    _, foh_h = make_user(db, tid, UserRole.FOH)
    assert client.get(f"{BASE}/content/{item.id}/variants", headers=foh_h).status_code == 403
    missing = svc.create_item(db, tid, kind="post", title="m", actor_id=None, payload={"caption": "m"})
    db.commit()
    body = client.get(f"{BASE}/content/{missing.id}/variants", headers=ws["mkt_h"]).json()
    assert body["variants"] == [] and body["problems"]
    assert agency is not None and MarketingContent is not None and runs is not None
