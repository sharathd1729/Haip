"""AI images: licence registry, opt-in, NVIDIA adapter (host pin, 202 polling, error classes), approval gate."""
import base64
import io
import uuid
from unittest.mock import patch

import httpx
import pytest
from PIL import Image

from app.adapters import image as image_adapter
from app.adapters.image import nvidia
from app.models.marketing import MarketingImageJob
from app.models.media_asset import MediaAsset
from app.models.usage_event import UsageEvent
from app.models.user import UserRole
from app.services import marketing_content_service as svc
from app.services import marketing_image_service as images
from tests.test_marketing_studio_content import BASE, enable_module, make_user, ws  # noqa: F401  (ws is a fixture)


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (896, 1152), (40, 90, 70)).save(buf, format="PNG")
    return buf.getvalue()


def _fake_store():
    return patch("app.services.media_storage.upload_marketing_media", side_effect=lambda t, c, m, e: f"{t}/marketing/{uuid.uuid4().hex}.{e}")


# ── Registry ────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", ["flux.1-dev", "stable-diffusion-3.5-large", "qwen-image", "nope"])
def test_blocked_or_unknown_models_cannot_be_used(key):
    with pytest.raises(image_adapter.ImageModelBlocked):
        image_adapter.get_model(key)


def test_only_commercially_licensed_confirmed_models_are_enabled():
    enabled = {k for k, m in image_adapter.MODELS.items() if m.enabled}
    assert enabled == {"gemini-3.1-flash-lite-image", "flux.1-schnell"}
    assert image_adapter.DEFAULT_MODEL == "gemini-3.1-flash-lite-image"
    assert "non-commercial" in image_adapter.MODELS["flux.1-dev"].licence


# ── NVIDIA adapter ──────────────────────────────────────────────────────────────────────────────────────────────────

def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok_body():
    return {"artifacts": [{"base64": base64.b64encode(_png()).decode(), "finishReason": "SUCCESS", "seed": 7}]}


@pytest.fixture()
def key(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setattr(nvidia, "POLL_EVERY", 0)


def test_adapter_success_and_202_polling(key):
    calls = []

    def handler(req: httpx.Request):
        calls.append(str(req.url))
        if req.url.host == "ai.api.nvidia.com":
            assert req.headers["authorization"] == "Bearer nvapi-test"
            return httpx.Response(202, headers={"NVCF-REQID": "req-1"})
        return httpx.Response(200, json=_ok_body())

    m = image_adapter.MODELS["flux.1-schnell"]
    raw, meta = nvidia.generate(m, "a caravan", 896, 1152, client=_client(handler))
    assert raw[:4] == b"\x89PNG" and meta["seed"] == 7 and meta["model"] == "flux.1-schnell"
    assert calls == ["https://ai.api.nvidia.com/v1/genai/black-forest-labs/flux.1-schnell",
                     "https://api.nvcf.nvidia.com/v2/nvcf/pexec/status/req-1"]


@pytest.mark.parametrize("status,transient", [(429, True), (503, True), (400, False), (422, False)])
def test_adapter_error_classes(key, status, transient):
    m = image_adapter.MODELS["flux.1-schnell"]
    with pytest.raises(image_adapter.ImageGenError) as exc:
        nvidia.generate(m, "x", 1024, 1024, client=_client(lambda r: httpx.Response(status, text="nope")))
    assert exc.value.transient is transient


def test_adapter_timeout_is_transient_and_filtered_image_is_not(key):
    m = image_adapter.MODELS["flux.1-schnell"]

    def slow(_):
        raise httpx.ReadTimeout("slow")
    with pytest.raises(image_adapter.ImageGenError) as exc:
        nvidia.generate(m, "x", 1024, 1024, client=_client(slow))
    assert exc.value.transient is True
    filtered = {"artifacts": [{"base64": "", "finishReason": "CONTENT_FILTERED"}]}
    with pytest.raises(image_adapter.ImageGenError) as exc:
        nvidia.generate(m, "x", 1024, 1024, client=_client(lambda r: httpx.Response(200, json=filtered)))
    assert exc.value.transient is False


def test_adapter_never_sends_the_key_to_another_host():
    with pytest.raises(image_adapter.ImageGenError):
        nvidia._check_host("https://evil.example.com/v1/genai/x")


# ── Opt-in + requests over the API ──────────────────────────────────────────────────────────────────────────────────

def test_off_by_default_and_only_owner_can_switch_on(client, ws):  # noqa: F811
    r = client.post(f"{BASE}/images", json={"prompt": "misty road at sunrise"}, headers=ws["mkt_h"])
    assert r.status_code == 403 and r.json()["detail"]["code"] == "ai_images_off"
    assert client.put(f"{BASE}/settings", json={"ai_images_enabled": True}, headers=ws["manager_h"]).status_code == 403
    r = client.put(f"{BASE}/settings", json={"ai_images_enabled": True}, headers=ws["owner_h"])
    assert r.status_code == 200 and r.json()["ai_images_enabled"] is True


def test_request_validates_model_and_text_then_queues(client, ws, monkeypatch):  # noqa: F811
    calls = []
    monkeypatch.setattr("app.workers.tasks.marketing_studio.generate_image",
                        type("FakeTask", (), {"delay": staticmethod(lambda *a: calls.append(a))}))
    client.put(f"{BASE}/settings", json={"ai_images_enabled": True}, headers=ws["owner_h"])
    r = client.post(f"{BASE}/images", json={"prompt": "misty road", "model": "flux.1-dev"}, headers=ws["mkt_h"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "model_not_allowed"
    r = client.post(f"{BASE}/images", json={"prompt": "poster saying Rs 9,999 per night"}, headers=ws["mkt_h"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "content_not_allowed"
    r = client.post(f"{BASE}/images", json={"prompt": "misty ghat road at sunrise", "shape": "story"}, headers=ws["mkt_h"])
    assert r.status_code == 202 and r.json()["status"] == "pending" and len(calls) == 1


# ── Run + approval gate ─────────────────────────────────────────────────────────────────────────────────────────────

def _job(db, ws, actor):  # noqa: F811
    tenant = ws["tenant"]
    images.set_ai_images(db, tenant, True, ws["owner"].id)
    job = images.request_image(db, tenant, prompt="misty ghat road at sunrise", model="flux.1-schnell", shape="portrait", actor_id=actor.id)
    db.commit()
    return job


def test_run_stores_pending_ai_asset_once_and_meters_it(db, ws):  # noqa: F811
    job = _job(db, ws, ws["mkt"])
    with _fake_store(), patch.object(image_adapter, "generate", return_value=(_png(), {"provider": "nvidia", "model": "flux.1-schnell"})) as gen:
        images.run_image(db, ws["tenant"].id, job.id)
        db.commit()
        images.run_image(db, ws["tenant"].id, job.id)      # redelivered task
    assert gen.call_count == 1 and job.status == "ready"
    asset = db.get(MediaAsset, job.asset_id)
    assert (asset.source, asset.status, asset.mime_type) == ("ai", "pending_review", "image/jpeg")
    assert asset.provenance["ai_generated"] is True and asset.provenance["prompt"] == job.prompt
    assert "no text" in gen.call_args.args[1]
    assert db.query(UsageEvent).filter_by(tenant_id=ws["tenant"].id, kind="image_gen").count() == 1


def test_transient_error_propagates_and_permanent_error_fails_the_job(db, ws):  # noqa: F811
    job = _job(db, ws, ws["mkt"])
    with patch.object(image_adapter, "generate", side_effect=image_adapter.ImageGenError("504", transient=True)):
        with pytest.raises(image_adapter.ImageGenError):
            images.run_image(db, ws["tenant"].id, job.id)
    with patch.object(image_adapter, "generate", side_effect=image_adapter.ImageGenError("400 bad", transient=False)):
        images.run_image(db, ws["tenant"].id, job.id)
    assert job.status == "failed" and "400" in job.error


def test_pending_ai_image_cannot_be_used_until_approved(db, ws):  # noqa: F811
    job = _job(db, ws, ws["manager"])
    with _fake_store(), patch.object(image_adapter, "generate", return_value=(_png(), {"provider": "nvidia"})):
        images.run_image(db, ws["tenant"].id, job.id)
    db.commit()
    item = svc.create_item(db, ws["tenant"].id, kind="post", title="x", actor_id=ws["mkt"].id)
    db.commit()
    payload = {"caption": "Morning on the ghats", "media": {"asset_id": job.asset_id}}
    with pytest.raises(svc.MarketingError) as exc:
        svc.add_version(db, ws["tenant"].id, item.id, payload, origin="human", actor_id=ws["mkt"].id)
    assert exc.value.code == "asset_not_usable"

    with pytest.raises(svc.MarketingError) as exc:      # the manager asked for it: no self-approval
        images.review_image(db, ws["tenant"].id, job.asset_id, ws["manager"], approve=True)
    assert exc.value.code == "self_approval"
    images.review_image(db, ws["tenant"].id, job.asset_id, ws["owner"], approve=True)
    db.commit()
    with pytest.raises(svc.MarketingError) as exc:      # already reviewed
        images.review_image(db, ws["tenant"].id, job.asset_id, ws["owner"], approve=True)
    assert exc.value.code == "wrong_state"
    v = svc.add_version(db, ws["tenant"].id, item.id, payload, origin="human", actor_id=ws["mkt"].id)
    assert v.payload["media"]["asset_id"] == job.asset_id


def test_another_tenants_asset_is_never_usable(db, ws):  # noqa: F811
    other = MediaAsset(tenant_id=str(uuid.uuid4()), storage_key="x", mime_type="image/png", bytes=1, sha256="0" * 64, status="active")
    item = svc.create_item(db, ws["tenant"].id, kind="post", title="x", actor_id=ws["mkt"].id)
    db.commit()
    with pytest.raises(svc.MarketingError) as exc:
        svc.add_version(db, ws["tenant"].id, item.id, {"caption": "x", "media": {"asset_id": other.id or "missing"}},
                        origin="human", actor_id=ws["mkt"].id)
    assert exc.value.code == "asset_not_usable"


def test_reject_archives_and_api_review_needs_approve_capability(client, db, ws):  # noqa: F811
    job = _job(db, ws, ws["mkt"])
    with _fake_store(), patch.object(image_adapter, "generate", return_value=(_png(), {"provider": "nvidia"})):
        images.run_image(db, ws["tenant"].id, job.id)
    db.commit()
    assert client.post(f"{BASE}/media/{job.asset_id}/approve", json={}, headers=ws["mkt_h"]).status_code == 403
    r = client.post(f"{BASE}/media/{job.asset_id}/reject", json={"note": "Looks fake"}, headers=ws["manager_h"])
    assert r.status_code == 200 and r.json()["status"] == "archived"


# ── Gemini adapter ──────────────────────────────────────────────────────────────────────────────────────────────────

from app.adapters.image import gemini  # noqa: E402

GEMINI_OK = {
    "candidates": [{"finishReason": "STOP", "content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": base64.b64encode(_png()).decode()}}]}}],
    "usageMetadata": {"promptTokenCount": 32, "candidatesTokenCount": 1617,
                      "candidatesTokensDetails": [{"modality": "IMAGE", "tokenCount": 1120}]},
}


@pytest.fixture()
def gkey(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.GEMINI_API_KEY", "g-test")


def test_gemini_success_sends_aspect_and_estimates_cost(gkey):
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["key"], seen["body"] = str(req.url), req.headers.get("x-goog-api-key"), req.content
        return httpx.Response(200, json=GEMINI_OK)

    m = image_adapter.MODELS["gemini-3.1-flash-lite-image"]
    raw, meta = gemini.generate(m, "misty road", "4:5", client=_client(handler))
    assert raw.startswith(bytes([0x89]) + b"PNG")
    assert seen["url"] == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite-image:generateContent"
    assert seen["key"] == "g-test" and b'"aspectRatio":"4:5"' in seen["body"].replace(b" ", b"")
    assert "key=" not in seen["url"]                                     # never in the URL
    assert (meta["image_tokens"], meta["text_tokens"], meta["input_tokens"]) == (1120, 497, 32)
    # 1120 * $30 + 497 * $1.50 + 32 * $0.25 per 1M tokens
    assert meta["est_cost_usd"] == pytest.approx(0.0343535, abs=1e-6)


@pytest.mark.parametrize("status,transient", [(429, True), (500, True), (400, False), (403, False)])
def test_gemini_error_classes(gkey, status, transient):
    m = image_adapter.MODELS["gemini-3.1-flash-lite-image"]
    with pytest.raises(image_adapter.ImageGenError) as exc:
        gemini.generate(m, "x", "1:1", client=_client(lambda r: httpx.Response(status, text="nope")))
    assert exc.value.transient is transient


@pytest.mark.parametrize("body", [
    {"promptFeedback": {"blockReason": "SAFETY"}},
    {"candidates": [{"finishReason": "IMAGE_SAFETY", "content": {"parts": []}}]},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "I can't draw that"}]}}]},
])
def test_gemini_refusals_are_permanent(gkey, body):
    m = image_adapter.MODELS["gemini-3.1-flash-lite-image"]
    with pytest.raises(image_adapter.ImageGenError) as exc:
        gemini.generate(m, "x", "1:1", client=_client(lambda r: httpx.Response(200, json=body)))
    assert exc.value.transient is False


def test_gemini_timeout_is_transient(gkey):
    def slow(_):
        raise httpx.ConnectTimeout("slow")
    with pytest.raises(image_adapter.ImageGenError) as exc:
        gemini.generate(image_adapter.MODELS["gemini-3.1-flash-lite-image"], "x", "1:1", client=_client(slow))
    assert exc.value.transient is True


# ── Monthly cap ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_monthly_cap_blocks_requests_and_failed_jobs_do_not_count(db, ws):  # noqa: F811
    tenant = ws["tenant"]
    images.set_ai_images(db, tenant, True, ws["owner"].id)
    images.set_monthly_cap(db, tenant, 2, ws["owner"].id)
    db.commit()
    a = images.request_image(db, tenant, prompt="misty road one", model=image_adapter.DEFAULT_MODEL, shape="portrait", actor_id=ws["mkt"].id)
    images.request_image(db, tenant, prompt="misty road two", model=image_adapter.DEFAULT_MODEL, shape="square", actor_id=ws["mkt"].id)
    db.commit()
    with pytest.raises(svc.MarketingError) as exc:
        images.request_image(db, tenant, prompt="misty road three", model=image_adapter.DEFAULT_MODEL, shape="story", actor_id=ws["mkt"].id)
    assert exc.value.code == "monthly_cap_reached" and exc.value.status == 429
    a.status = "failed"
    db.commit()
    assert images.used_this_month(db, tenant) == 1
    images.request_image(db, tenant, prompt="misty road three", model=image_adapter.DEFAULT_MODEL, shape="story", actor_id=ws["mkt"].id)


def test_cap_settings_api_owner_only_and_bounded(client, ws):  # noqa: F811
    r = client.get(f"{BASE}/settings", headers=ws["mkt_h"])
    assert r.json()["ai_images_monthly_cap"] == images.DEFAULT_MONTHLY_CAP and r.json()["default_model"] == image_adapter.DEFAULT_MODEL
    assert client.put(f"{BASE}/settings", json={"ai_images_monthly_cap": 10}, headers=ws["manager_h"]).status_code == 403
    assert client.put(f"{BASE}/settings", json={"ai_images_monthly_cap": 5000}, headers=ws["owner_h"]).status_code == 422
    r = client.put(f"{BASE}/settings", json={"ai_images_monthly_cap": 10}, headers=ws["owner_h"])
    assert r.status_code == 200 and r.json()["ai_images_monthly_cap"] == 10 and r.json()["ai_images_enabled"] is False


def test_generated_image_records_cost_in_usage(db, ws):  # noqa: F811
    job = _job(db, ws, ws["mkt"])
    job.model = image_adapter.DEFAULT_MODEL
    db.commit()
    meta = {"provider": "gemini", "input_tokens": 32, "image_tokens": 1120, "text_tokens": 497, "est_cost_usd": 0.034}
    with _fake_store(), patch.object(image_adapter, "generate", return_value=(_png(), meta)):
        images.run_image(db, ws["tenant"].id, job.id)
    db.commit()
    ev = db.query(UsageEvent).filter_by(tenant_id=ws["tenant"].id, kind="image_gen").one()
    assert (ev.provider, ev.input_units, ev.output_units, ev.meta["est_cost_usd"]) == ("gemini", 32, 1617, 0.034)
