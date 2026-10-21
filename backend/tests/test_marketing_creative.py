"""Agency M2b (21 Oct 2026): Canva brand-template designs and Higgsfield videos, against fake HTTP transports."""
import base64
import hashlib
import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from PIL import Image

from app.adapters import canva as canva_api
from app.adapters import video as video_api
from app.core.encryption import decrypt_credentials, encrypt_credentials
from app.models.audit_event import AuditEvent
from app.models.integration import Integration
from app.models.marketing import MarketingCreativeJob
from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.services import marketing_canva_service as canva
from app.services import marketing_content_service as svc
from app.services import marketing_video_service as video
from tests.test_marketing_studio_content import BASE, ws  # noqa: F401  (fixture)


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (1080, 1350), (200, 120, 40)).save(out, format="JPEG")
    return out.getvalue()


def _asset(db, tid, **kw):
    a = MediaAsset(id=str(uuid.uuid4()), tenant_id=tid, storage_key=f"{tid}/m/{uuid.uuid4().hex}.jpg", mime_type="image/jpeg",
                   bytes=10, sha256=uuid.uuid4().hex * 2, status="active", **kw)
    db.add(a)
    db.commit()
    return a


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.CANVA_CLIENT_ID", "cid")
    monkeypatch.setattr("app.core.config.settings.CANVA_CLIENT_SECRET", "csecret")
    monkeypatch.setattr("app.core.config.settings.API_BASE_URL", "https://api.haip.test")
    monkeypatch.setattr("app.services.media_storage.upload_marketing_media", lambda t, c, m, e: f"{t}/marketing/{uuid.uuid4().hex}.{e}")


class FakeRedis:
    def __init__(self):
        self.d = {}

    def setex(self, k, ttl, v):
        self.d[k] = v

    def eval(self, script, n, k):
        return self.d.pop(k, None)


# ── Canva adapter ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_pkce_and_authorize_url():
    verifier, challenge = canva_api.pkce_pair()
    assert challenge == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    q = parse_qs(urlparse(canva_api.authorize_url("cid", "https://api.haip.test/cb", "st", challenge)).query)
    assert q["code_challenge_method"] == ["S256"] and q["response_type"] == ["code"] and q["state"] == ["st"]
    assert "brandtemplate:content:read" in q["scope"][0] and "asset:write" in q["scope"][0]


def test_token_exchange_uses_basic_auth_and_a_form_body():
    seen = {}

    def handler(req):
        seen.update(url=str(req.url), auth=req.headers["authorization"], body=parse_qs(req.content.decode()))
        return httpx.Response(200, json={"access_token": "a1", "refresh_token": "r1", "expires_in": 14400})
    tok = canva_api.exchange_code("cid", "csecret", "code1", "ver1", "https://cb", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert tok["refresh_token"] == "r1" and seen["url"] == "https://api.canva.com/rest/v1/oauth/token"
    assert seen["auth"] == "Basic " + base64.b64encode(b"cid:csecret").decode()
    assert seen["body"] == {"grant_type": ["authorization_code"], "code": ["code1"], "code_verifier": ["ver1"], "redirect_uri": ["https://cb"]}


def test_export_downloads_only_from_canva_hosts():
    api = canva_api.Canva("t", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x"))))
    with pytest.raises(canva_api.CanvaError):
        api.download("https://evil.example.com/x.jpg")
    assert api.download("https://export-download.canva.com/x.jpg") == b"x"


# ── Canva service ───────────────────────────────────────────────────────────────────────────────────────────────────

def _connect(db, tid, expires_in=3600, refresh="r1"):
    integ = Integration(tenant_id=tid, kind="canva", status="active",
                        credentials_kms_blob=encrypt_credentials({"access_token": "a1", "refresh_token": refresh}),
                        config={"expires_at": (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()})
    db.add(integ)
    db.commit()
    return integ


def test_oauth_round_trip_stores_encrypted_tokens_and_state_is_single_use(db, ws, monkeypatch):  # noqa: F811
    r = FakeRedis()
    monkeypatch.setattr(canva, "_redis", lambda: r)
    url = canva.start_oauth(ws["tenant"].id, ws["owner"].id)
    state = parse_qs(urlparse(url).query)["state"][0]
    stored = json.loads(r.d[f"oauth:canva:{state}"])
    assert stored["tenant_id"] == ws["tenant"].id and stored["verifier"] not in url       # verifier never leaves HAIP
    http = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={
        "access_token": "a1", "refresh_token": "r1", "expires_in": 14400, "scope": "x"})))
    assert canva.finish_oauth(db, "code", state, http=http) == ws["tenant"].id
    db.commit()
    integ = canva.connection(db, ws["tenant"].id)
    assert decrypt_credentials(integ.credentials_kms_blob)["refresh_token"] == "r1"
    assert db.query(AuditEvent).filter_by(tenant_id=ws["tenant"].id, action="marketing.canva.connected").count() == 1
    with pytest.raises(svc.MarketingError) as exc:
        canva.finish_oauth(db, "code", state, http=http)
    assert exc.value.code == "state_expired"


def test_expired_token_is_refreshed_and_the_new_single_use_refresh_token_kept(db, ws):  # noqa: F811
    _connect(db, ws["tenant"].id, expires_in=-60, refresh="old")
    seen = []

    def handler(req):
        seen.append(parse_qs(req.content.decode()))
        return httpx.Response(200, json={"access_token": "a2", "refresh_token": "new", "expires_in": 14400})
    api = canva.client(db, ws["tenant"].id, http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert seen[0]["refresh_token"] == ["old"] and api._h["Authorization"] == "Bearer a2"
    assert decrypt_credentials(canva.connection(db, ws["tenant"].id).credentials_kms_blob)["refresh_token"] == "new"


def test_rejected_refresh_asks_to_reconnect(db, ws):  # noqa: F811
    _connect(db, ws["tenant"].id, expires_in=-60)
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"error": "invalid_grant"})))
    with pytest.raises(svc.MarketingError) as exc:
        canva.client(db, ws["tenant"].id, http=http)
    assert exc.value.code == "canva_reconnect"
    assert db.query(Integration).filter_by(tenant_id=ws["tenant"].id, kind="canva").one().status == "error"


def test_field_mapping_by_name():
    data = canva.field_data({"Headline": "text", "Body copy": "text", "CTA button": "text", "Hero photo": "image",
                             "Logo": "image", "Unknown": "text"}, "carousel",
                            {"caption": "x", "slides": [{"headline": "Day 1", "body": "Coorg", "media": {"asset_id": "a"}},
                                                        {"headline": "Day 2", "media": {"asset_id": "b"}}]},
                            {"a": "ca", "b": "cb"})
    assert data["Headline"] == {"type": "text", "text": "Day 1"} and data["Body copy"]["text"] == "Coorg"
    assert data["Hero photo"]["asset_id"] == "ca" and data["Logo"]["asset_id"] == "cb" and "Unknown" not in data
    assert "CTA button" not in data                                              # the draft has no CTA: template default


def _canva_api(calls, dataset=None):
    def handler(req):
        p = req.url.path
        calls.append((req.method, p))
        if p.endswith("/dataset"):
            return httpx.Response(200, json={"dataset": dataset or {"headline": {"type": "text"}, "photo": {"type": "image"}}})
        if p.endswith("/asset-uploads"):
            return httpx.Response(200, json={"job": {"id": "u1", "status": "success", "asset": {"id": "canva-asset"}}})
        if p.endswith("/autofills"):
            return httpx.Response(200, json={"job": {"id": "f1", "status": "in_progress"}})
        if p.endswith("/autofills/f1"):
            return httpx.Response(200, json={"job": {"id": "f1", "status": "success", "result": {"type": "create_design",
                                  "design": {"id": "D1", "url": "https://www.canva.com/design/D1/edit"}}}})
        if p.endswith("/exports"):
            return httpx.Response(200, json={"job": {"id": "e1", "status": "success", "urls": ["https://export-download.canva.com/D1.jpg"]}})
        if req.url.host == "export-download.canva.com":
            return httpx.Response(200, content=_jpeg())
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_design_from_a_draft_lands_in_the_library_with_the_edit_link(db, ws, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.adapters.canva.time.sleep", lambda s: None)
    tid = ws["tenant"].id
    _connect(db, tid)
    photo = _asset(db, tid, alt_text="pool")
    item = svc.create_item(db, tid, kind="post", title="Pool evenings", actor_id=ws["mkt"].id,
                           payload={"caption": "x", "overlay_text": "Evenings by the pool", "media": {"asset_id": photo.id}})
    db.commit()
    job = canva.request_design(db, ws["tenant"], item.id, "T1", ws["mkt"].id)
    db.commit()
    calls = []
    canva.run_design(db, ws["tenant"], job.id, http=_canva_api(calls), read_bytes=lambda k: _jpeg())
    db.commit()
    assert job.status == "ready" and job.external_id == "D1" and job.external_url.endswith("/edit")
    asset = db.get(MediaAsset, job.asset_id)
    assert asset.source == "canva" and asset.status == "active" and asset.provenance["content_id"] == item.id
    assert ("POST", "/rest/v1/asset-uploads") in calls and ("POST", "/rest/v1/exports") in calls


def test_template_without_fillable_fields_fails_with_advice(db, ws, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.adapters.canva.time.sleep", lambda s: None)
    tid = ws["tenant"].id
    _connect(db, tid)
    item = svc.create_item(db, tid, kind="post", title="x", actor_id=ws["mkt"].id, payload={"caption": "x"})
    db.commit()
    job = canva.request_design(db, ws["tenant"], item.id, "T1", ws["mkt"].id)
    canva.run_design(db, ws["tenant"], job.id, http=_canva_api([], dataset={"Mystery": {"type": "text"}}))
    assert job.status == "failed" and "headline, body, cta, photo" in job.error


def test_canva_api_endpoints(client, db, ws, monkeypatch):  # noqa: F811
    r = client.get(f"{BASE}/creative", headers=ws["mkt_h"])
    assert r.status_code == 200 and r.json()["canva"] == {"available": True, "connected": False}
    assert client.get(f"{BASE}/canva/templates", headers=ws["mkt_h"]).json()["detail"]["code"] == "canva_not_connected"
    item = svc.create_item(db, ws["tenant"].id, kind="post", title="x", actor_id=ws["mkt"].id, payload={"caption": "x"})
    db.commit()
    assert client.post(f"{BASE}/content/{item.id}/canva", json={"template_id": "T1"}, headers=ws["mkt_h"]).status_code == 409
    _connect(db, ws["tenant"].id)
    queued = []
    monkeypatch.setattr("app.workers.tasks.marketing_studio.canva_design.delay", lambda *a: queued.append(a))
    r = client.post(f"{BASE}/content/{item.id}/canva", json={"template_id": "T1"}, headers=ws["mkt_h"])
    assert r.status_code == 202 and queued == [(ws["tenant"].id, r.json()["id"])]
    assert client.delete(f"{BASE}/canva", headers=ws["manager_h"]).status_code == 403
    assert client.delete(f"{BASE}/canva", headers=ws["owner_h"]).json() == {"disconnected": True}


# ── Higgsfield ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _video_ready(client, ws):  # noqa: F811
    assert client.put(f"{BASE}/higgsfield", json={"key_id": "hf-key-123", "key_secret": "hf-secret-456"},
                      headers=ws["owner_h"]).status_code == 200
    assert client.put(f"{BASE}/video-settings", json={"enabled": True, "monthly_seconds": 10}, headers=ws["owner_h"]).status_code == 200


def test_higgsfield_key_is_owner_only_encrypted_and_never_returned(client, db, ws):  # noqa: F811
    assert client.put(f"{BASE}/higgsfield", json={"key_id": "hf-key-123", "key_secret": "hf-secret-456"},
                      headers=ws["manager_h"]).status_code == 403
    r = client.put(f"{BASE}/higgsfield", json={"key_id": "hf-key-123", "key_secret": "hf-secret-456"}, headers=ws["owner_h"])
    assert r.status_code == 200 and "hf-secret" not in r.text
    integ = video.connection(db, ws["tenant"].id)
    assert decrypt_credentials(integ.credentials_kms_blob)["key_secret"] == "hf-secret-456"
    assert "hf-secret" not in client.get(f"{BASE}/creative", headers=ws["mkt_h"]).text


def test_video_requests_are_gated(client, db, ws, monkeypatch):  # noqa: F811
    tid = ws["tenant"].id
    a = _asset(db, tid)
    body = {"asset_ids": [a.id], "prompt": "slow push in over the pool", "duration": 5}
    assert client.post(f"{BASE}/videos", json=body, headers=ws["mkt_h"]).json()["detail"]["code"] == "video_off"
    _video_ready(client, ws)
    people = _asset(db, tid, tags={"people": True, "subjects": ["people"]})
    r = client.post(f"{BASE}/videos", json={**body, "asset_ids": [people.id]}, headers=ws["mkt_h"])
    assert r.json()["detail"]["code"] == "people_consent"
    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    theirs = _asset(db, other.id)
    assert client.post(f"{BASE}/videos", json={**body, "asset_ids": [theirs.id]}, headers=ws["mkt_h"]).json()["detail"]["code"] == "photo_unavailable"
    queued = []
    monkeypatch.setattr("app.workers.tasks.marketing_studio.video_submit.delay", lambda *x: queued.append(x))
    r = client.post(f"{BASE}/videos", json=body, headers=ws["mkt_h"])
    assert r.status_code == 202 and len(queued) == 1
    client.post(f"{BASE}/videos", json=body, headers=ws["mkt_h"])               # 10 of 10 seconds used
    r = client.post(f"{BASE}/videos", json=body, headers=ws["mkt_h"])
    assert r.json()["detail"]["code"] == "video_cap_reached"


def _hf(seen, states):
    def handler(req):
        seen.append((req.method, req.url.path, dict(req.headers)))
        if req.method == "POST":
            return httpx.Response(200, json={"status": "queued", "request_id": "R1"})
        if req.url.host == "cdn.higgsfield.example":
            return httpx.Response(200, content=b"\x00\x00\x00\x18ftypmp42")
        return httpx.Response(200, json=states.pop(0))
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_submit_once_then_poll_until_the_clip_is_stored_for_approval(client, db, ws, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.core.url_safety.assert_public_url", lambda url, allow_http=True: None)
    tid = ws["tenant"].id
    _video_ready(client, ws)
    a = _asset(db, tid)
    job = video.request_video(db, ws["tenant"], [a.id], "slow push in", 5, ws["mkt"].id)
    db.commit()
    seen = []
    http = _hf(seen, [{"status": "in_progress"}, {"status": "completed", "video": {"url": "https://cdn.higgsfield.example/v.mp4"}}])
    video.submit(db, ws["tenant"], job.id, http=http, url_for=lambda x: f"https://signed/{x.id}")
    method, path, headers = seen[0]
    assert path == "/bytedance/seedance-2.5/reference-to-video" and headers["authorization"] == "Key hf-key-123:hf-secret-456"
    assert headers["idempotency-key"] == job.idempotency_key and job.external_id == "R1" and job.status == "running"
    video.submit(db, ws["tenant"], job.id, http=http)                            # re-delivered task: no second submit
    assert sum(1 for m, *_ in seen if m == "POST") == 1
    video.poll(db, ws["tenant"], job.id, http=http)
    assert job.status == "running"
    video.poll(db, ws["tenant"], job.id, http=http)
    db.commit()
    clip = db.get(MediaAsset, job.asset_id)
    assert job.status == "ready" and clip.mime_type == "video/mp4" and clip.status == "pending_review" and clip.source == "ai"


def test_moderation_rejection_fails_the_job(client, db, ws):  # noqa: F811
    _video_ready(client, ws)
    a = _asset(db, ws["tenant"].id)
    job = video.request_video(db, ws["tenant"], [a.id], "slow push in", 5, ws["mkt"].id)
    seen = []
    http = _hf(seen, [{"status": "nsfw"}])
    video.submit(db, ws["tenant"], job.id, http=http, url_for=lambda x: "https://signed/x")
    video.poll(db, ws["tenant"], job.id, http=http)
    assert job.status == "failed" and "content check" in job.error
    db.commit()
    assert db.query(MarketingCreativeJob).filter_by(tenant_id=ws["tenant"].id, status="failed").count() == 1


def test_private_download_addresses_are_refused():
    api = video_api.Higgsfield("k" * 8, "s" * 8, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))))
    with pytest.raises(video_api.VideoError):
        api.download("https://127.0.0.1/v.mp4")
