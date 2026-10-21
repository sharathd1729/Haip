"""Agency M3 (21 Oct 2026): reels from the property's own clips -- upload, cut, captions, cover, publish as REELS.

Real ffmpeg runs (tiny synthetic clips); the module is skipped where ffmpeg is not installed. No network, no storage.
"""
import io
import json
import shutil
import subprocess
import uuid
from datetime import datetime, timezone

import pytest
from PIL import Image

from app.models.marketing import MarketingContent
from app.models.media_asset import MediaAsset
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.schemas.marketing import validate_content
from app.services import marketing_channels as channels
from app.services import marketing_content_service as svc
from app.services import marketing_lint
from app.services import marketing_photos as photos
from app.services import marketing_publish_service as pub
from app.services import marketing_reel as reel
from tests.test_marketing_publish import FakePublisher
from tests.test_marketing_studio_content import BASE, make_user, ws  # noqa: F401  (fixture)

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                                reason="ffmpeg is not installed")


def _clip(tmp_path, seconds=3, size="320x180", audio=True, name="c.mov") -> bytes:
    """A synthetic clip WITH a sound track and a title tag, so the test can prove both are stripped."""
    out = tmp_path / name
    args = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size={size}:rate=30"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    args += ["-metadata", "title=Guest at the pool", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(out)]
    subprocess.run(args, check=True, capture_output=True)
    return out.read_bytes()


def _jpeg(colour=(30, 110, 80)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (1200, 900), colour).save(out, format="JPEG")
    return out.getvalue()


def _streams(data: bytes, tmp_path) -> dict:
    path = tmp_path / f"{uuid.uuid4().hex}.mp4"
    path.write_bytes(data)
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                         check=True, capture_output=True)
    return json.loads(out.stdout)


@pytest.fixture
def store(monkeypatch):
    """In-memory object store: upload -> key, _read_object(key) -> bytes."""
    objects: dict[str, bytes] = {}

    def upload(t, content, mime, ext):
        key = f"{t}/marketing/{uuid.uuid4().hex}.{ext}"
        objects[key] = content
        return key
    monkeypatch.setattr("app.services.media_storage.upload_marketing_media", upload)
    monkeypatch.setattr("app.services.media_library_service._read_object", lambda key: objects[key])
    return objects


def _photo(db, tid, store, alt="the deck at dawn"):
    key = f"{tid}/marketing/{uuid.uuid4().hex}.jpg"
    store[key] = _jpeg()
    a = MediaAsset(id=str(uuid.uuid4()), tenant_id=tid, storage_key=key, mime_type="image/jpeg", bytes=10,
                   sha256=uuid.uuid4().hex * 2, status="active", alt_text=alt)
    db.add(a)
    db.commit()
    return a


# ── Clips ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_clip_upload_strips_sound_and_metadata_and_records_length(client, db, ws, store, tmp_path):  # noqa: F811
    raw = _clip(tmp_path)
    r = client.post(f"{BASE}/media/clips", files={"file": ("pool.mov", raw, "video/quicktime")},
                    data={"alt_text": "pool at sunset"}, headers=ws["mkt_h"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["mime_type"] == "video/mp4" and 2900 <= body["duration_ms"] <= 3100 and (body["width"], body["height"]) == (320, 180)
    asset = db.get(MediaAsset, body["id"])
    info = _streams(store[asset.storage_key], tmp_path)
    assert [s["codec_type"] for s in info["streams"]] == ["video"]                # no audio track survives
    assert "title" not in (info["format"].get("tags") or {})                      # no metadata survives
    assert asset.tenant_id == ws["tenant"].id and asset.status == "active"


def test_clip_upload_rejects_non_video_long_clips_and_wrong_roles(client, db, ws, store, tmp_path, monkeypatch):  # noqa: F811
    r = client.post(f"{BASE}/media/clips", files={"file": ("x.mp4", b"not a video at all", "video/mp4")}, headers=ws["mkt_h"])
    assert r.status_code in (415, 422)
    monkeypatch.setattr(reel, "MAX_CLIP_SECONDS", 2)
    r = client.post(f"{BASE}/media/clips", files={"file": ("long.mov", _clip(tmp_path, seconds=3), "video/mp4")},
                    headers=ws["mkt_h"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "clip_length"
    _, foh_h = make_user(db, ws["tenant"].id, UserRole.FOH)
    assert client.post(f"{BASE}/media/clips", files={"file": ("c.mov", b"x", "video/mp4")}, headers=foh_h).status_code == 403
    assert db.query(MediaAsset).filter_by(tenant_id=ws["tenant"].id).count() == 0


def test_clips_are_never_tagged_or_used_outside_reels(db, ws, store, tmp_path):  # noqa: F811
    tid = ws["tenant"].id
    clip = reel.add_clip(db, tid, _clip(tmp_path), actor_id=ws["mkt"].id, alt_text="pool")
    db.commit()
    from app.services import marketing_vision as vision
    assert clip.id not in vision.untagged(db, tid)
    assert clip.id not in [a.id for a in photos.library(db, tid)]
    assert clip.id in [a.id for a in photos.library(db, tid, videos=True)]


# ── Payload rules ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_reel_payload_limits_and_where_it_can_go():
    clip = {"seconds": 5, "caption": "Mist at 7am"}
    ok = validate_content("reel", {"caption": "Coorg", "clips": [clip, clip], "cover_clip": 1})
    assert ok["kind"] == "reel" and ok["clips"][0]["start_s"] == 0
    with pytest.raises(ValueError):
        validate_content("reel", {"caption": "x", "clips": [{"seconds": 15}] * 5})              # 75 s > 60 s
    with pytest.raises(ValueError):
        validate_content("reel", {"caption": "x", "clips": [clip, clip], "cover_clip": 2})
    assert channels.channels_for("reel") == ("instagram",)
    where = [w for w, _ in marketing_lint.segments("reel", {"caption": "c", "cover_text": "Slow", "clips": [clip, {}]})]
    assert where == ["cover", "clip 1", "caption"]


def test_picker_fills_reel_slots_with_clips_first(db, ws, store, tmp_path):  # noqa: F811
    tid = ws["tenant"].id
    still = _photo(db, tid, store, alt="pool at sunset")
    clip = reel.add_clip(db, tid, _clip(tmp_path), actor_id=ws["mkt"].id, alt_text="pool at sunset")
    db.commit()
    item = svc.create_item(db, tid, kind="reel", title="Pool", actor_id=None, payload={
        "caption": "Pool", "clips": [{"media": {"alt_text": "pool at sunset"}}, {"media": {"alt_text": "pool at sunset"}}]})
    db.commit()
    assert photos.attach_photos(db, ws["tenant"], item.id) == 2
    v = svc.get_version(db, tid, item.current_version_id)
    assert v.payload["clips"][0]["media"]["asset_id"] == clip.id and v.payload["clips"][1]["media"]["asset_id"] == still.id


# ── Render ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def _reel_payload(clip, still):
    return {"caption": "Coorg, slowly.", "hashtags": ["#coorg"], "cover_text": "Mist at 7am", "cover_clip": 0,
            "design": {"style": "overlay", "colour": "#1E7A5A", "accent": "#E0694A"},
            "clips": [{"media": {"asset_id": clip.id}, "start_s": 0.5, "seconds": 2, "caption": "The deck at dawn"},
                      {"media": {"asset_id": still.id}, "seconds": 2, "caption": "Coffee on the estate"}]}


def test_render_cuts_a_vertical_silent_reel_with_a_cover_and_reuses_it(db, ws, store, tmp_path):  # noqa: F811
    tenant = ws["tenant"]
    clip = reel.add_clip(db, tenant.id, _clip(tmp_path, seconds=4), actor_id=ws["mkt"].id, alt_text="deck")
    still = _photo(db, tenant.id, store)
    payload = _reel_payload(clip, still)
    video, cover = reel.render_reel(db, tenant, payload)
    db.commit()
    info = _streams(store[video.storage_key], tmp_path)
    v = info["streams"][0]
    assert [s["codec_type"] for s in info["streams"]] == ["video"] and (v["width"], v["height"]) == (1080, 1920)
    assert v["codec_name"] == "h264" and 3800 <= video.duration_ms <= 4200 and video.status == "derived"
    assert Image.open(io.BytesIO(store[cover.storage_key])).size == (1080, 1920) and cover.status == "derived"
    assert (video.provenance or {})["cover_asset_id"] == cover.id
    assert reel.render_reel(db, tenant, payload)[0].id == video.id                # same payload: no second render
    assert reel.find_render(db, tenant, {**payload, "cover_text": "Other"}) == (None, None)
    assert video.id not in [a.id for a in photos.library(db, tenant.id, videos=True)]   # never a source clip


def test_storyboard_preview_draws_a_still_per_clip(client, db, ws, store, tmp_path, monkeypatch):  # noqa: F811
    tid = ws["tenant"].id
    clip = reel.add_clip(db, tid, _clip(tmp_path), actor_id=ws["mkt"].id, alt_text="deck")
    still = _photo(db, tid, store)
    item = svc.create_item(db, tid, kind="reel", title="Deck", actor_id=None, payload=_reel_payload(clip, still))
    db.commit()
    body = client.get(f"{BASE}/content/{item.id}/preview", headers=ws["mkt_h"]).json()
    assert body["problems"] == [] and len(body["frames"]) == 2
    assert client.get(f"{BASE}/content/{item.id}/reel", headers=ws["mkt_h"]).json()["ready"] is False
    queued = []
    import app.workers.tasks.marketing_studio as tasks
    monkeypatch.setattr(tasks.render_reel, "delay", lambda *a: queued.append(a))
    assert client.post(f"{BASE}/content/{item.id}/reel/render", headers=ws["mkt_h"]).status_code == 202
    assert queued == [(tid, item.id, item.current_version_id)]
    from tests.test_marketing_agency_m0 import _Ctx
    monkeypatch.setattr(tasks, "SessionLocal", lambda: _Ctx(db))
    tasks.render_reel(tid, item.id, item.current_version_id)                   # what the worker runs
    assert client.get(f"{BASE}/content/{item.id}/reel", headers=ws["mkt_h"]).json()["ready"] is True

    other = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    theirs = svc.create_item(db, other.id, kind="reel", title="t", actor_id=None,
                             payload={"caption": "t", "clips": [{"seconds": 2}, {"seconds": 2}]})
    db.commit()
    assert client.get(f"{BASE}/content/{theirs.id}/reel", headers=ws["mkt_h"]).status_code == 404
    post = svc.create_item(db, tid, kind="post", title="p", actor_id=None, payload={"caption": "p"})
    db.commit()
    assert client.post(f"{BASE}/content/{post.id}/reel/render", headers=ws["mkt_h"]).status_code == 422


# ── Publish ─────────────────────────────────────────────────────────────────────────────────────────────────────────

class ReelPublisher(FakePublisher):
    def reel_container(self, video_url, *, caption, cover_url=None):
        self.n += 1
        self.calls.append(("reel", video_url, caption, cover_url))
        return f"r{self.n}"


def test_an_approved_reel_is_posted_as_reels_with_its_cover(db, ws, store, tmp_path):  # noqa: F811
    tenant = ws["tenant"]
    clip = reel.add_clip(db, tenant.id, _clip(tmp_path), actor_id=ws["mkt"].id, alt_text="deck")
    still = _photo(db, tenant.id, store)
    item = svc.create_item(db, tenant.id, kind="reel", title="Deck", actor_id=ws["mkt"].id,
                           payload=_reel_payload(clip, still))
    db.commit()
    svc.submit(db, tenant.id, item.id, item.current_version_id, ws["mkt"])
    svc.approve(db, tenant.id, item.id, item.current_version_id, ws["owner"])
    db.commit()
    attempt = pub.schedule(db, tenant, item.id, datetime.now(timezone.utc), ws["owner"].id)
    db.commit()
    fake = ReelPublisher()
    pub.publish_attempt(db, attempt.id, publisher_factory=lambda d, t: fake, media_url=lambda a: f"https://cdn/{a.id}")
    video, cover = reel.find_render(db, tenant, svc.get_version(db, tenant.id, item.approved_version_id).payload)
    assert attempt.status == "published", attempt.error
    assert fake.calls[0] == ("reel", f"https://cdn/{video.id}", "Coorg, slowly.\n\n#coorg", f"https://cdn/{cover.id}")
    assert ("publish", "r1") in fake.calls and db.get(MarketingContent, item.id).status == "published"
