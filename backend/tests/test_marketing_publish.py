"""Scheduler + publisher (agency phase C): approval gate, preflight, idempotency, retries, kill switch, autopilot."""
import io
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from PIL import Image

from app.adapters.instagram.publishing import PublishError, Publisher
from app.models.audit_event import AuditEvent
from app.models.marketing import MarketingContent, MarketingPublishAttempt
from app.models.media_asset import MediaAsset
from app.services import marketing_agency_service as agency
from app.services import marketing_content_service as svc
from app.services import marketing_publish_service as pub
from tests.test_marketing_studio_content import BASE, ws  # noqa: F401  (fixture)


class FakePublisher:
    def __init__(self, quota=10, fail=None, status=None):
        self.calls, self.quota, self.fail, self.status = [], quota, fail or {}, status or {}
        self.n = 0

    def _maybe_fail(self, name):
        if name in self.fail:
            raise self.fail[name]

    def quota_left(self):
        self._maybe_fail("quota")
        return self.quota

    def image_container(self, url, caption=None, carousel_item=False, story=False):
        self._maybe_fail("container")
        self.n += 1
        self.calls.append(("container", url, caption, carousel_item, story))
        return f"c{self.n}"

    def carousel_container(self, children, caption):
        self.calls.append(("carousel", tuple(children), caption))
        return "parent"

    def container_status(self, cid):
        return self.status.get(cid, "FINISHED")

    def wait_ready(self, cid):
        self._maybe_fail("wait")

    def publish(self, cid):
        self._maybe_fail("publish")
        self.calls.append(("publish", cid))
        return f"m-{cid}"

    def comment(self, media_id, message):
        self.calls.append(("comment", media_id, message))

    def permalink(self, media_id):
        return f"https://www.instagram.com/p/{media_id}/"

    def close(self):
        pass


def _photo_bytes(colour=(40, 120, 90)):
    out = io.BytesIO()
    Image.new("RGB", (1600, 1200), colour).save(out, format="JPEG")
    return out.getvalue()


PHOTO = _photo_bytes()


@pytest.fixture(autouse=True)
def _fake_storage(monkeypatch):
    stored = []

    def upload(t, content, mime, ext):
        stored.append((content, mime))
        return f"{t}/marketing/{uuid.uuid4().hex}.{ext}"
    monkeypatch.setattr("app.services.media_storage.upload_marketing_media", upload)
    return stored


def _jpeg(db, tid):
    a = MediaAsset(id=str(uuid.uuid4()), tenant_id=tid, storage_key=f"{tid}/marketing/{uuid.uuid4().hex}.jpg",
                   mime_type="image/jpeg", bytes=10, sha256=uuid.uuid4().hex * 2, status="active")
    db.add(a)
    db.commit()
    return a


def _approved(db, ws, kind="post", payload=None):  # noqa: F811
    tid = ws["tenant"].id
    if payload is None:
        a = _jpeg(db, tid)
        payload = {"caption": "Coorg, slowly.", "hashtags": ["#coorg"], "first_comment": "Where next?", "media": {"asset_id": a.id}}
    item = svc.create_item(db, tid, kind=kind, title="x", actor_id=ws["mkt"].id, payload=payload)
    db.commit()
    svc.submit(db, tid, item.id, item.current_version_id, ws["mkt"])
    svc.approve(db, tid, item.id, item.current_version_id, ws["owner"])
    db.commit()
    return item


def _run(db, attempt, fake):
    return pub.publish_attempt(db, attempt.id, publisher_factory=lambda d, t: fake, media_url=lambda a: f"https://cdn/{a.id}.jpg",
                               read_bytes=lambda key: PHOTO)


def _aware(dt):
    """SQLite hands back naive datetimes after a refresh (PostgreSQL keeps the offset)."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _due(db, attempt):
    attempt.scheduled_for = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()


# ── Scheduling rules ────────────────────────────────────────────────────────────────────────────────────────────────

def test_only_approved_publishable_content_can_be_scheduled(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    draft = svc.create_item(db, tid, kind="post", title="x", actor_id=ws["mkt"].id, payload={"caption": "hi"})
    db.commit()
    with pytest.raises(svc.MarketingError) as exc:
        pub.schedule(db, ws["tenant"], draft.id, datetime.now(timezone.utc), ws["owner"].id)
    assert exc.value.code == "not_approved"

    no_photo = _approved(db, ws, payload={"caption": "no photo"})
    with pytest.raises(svc.MarketingError) as exc:
        pub.schedule(db, ws["tenant"], no_photo.id, datetime.now(timezone.utc), ws["owner"].id)
    assert exc.value.code == "not_publishable" and "photo" in exc.value.problems[0]

    gif = MediaAsset(id=str(uuid.uuid4()), tenant_id=tid, storage_key="k", mime_type="image/gif", bytes=1, sha256="1" * 64, status="active")
    png = MediaAsset(id=str(uuid.uuid4()), tenant_id=tid, storage_key="k2", mime_type="image/png", bytes=1, sha256="2" * 64, status="active")
    db.add_all([gif, png])
    db.commit()
    as_gif = _approved(db, ws, payload={"caption": "gif", "media": {"asset_id": gif.id}})
    with pytest.raises(svc.MarketingError) as exc:
        pub.schedule(db, ws["tenant"], as_gif.id, datetime.now(timezone.utc), ws["owner"].id)
    assert "JPEG, PNG or WebP" in exc.value.problems[0]
    as_png = _approved(db, ws, payload={"caption": "png", "media": {"asset_id": png.id}})
    assert pub.schedule(db, ws["tenant"], as_png.id, datetime.now(timezone.utc), ws["owner"].id).status == "scheduled"


def test_schedule_api_needs_approve_capability(client, db, ws):  # noqa: F811
    item = _approved(db, ws)
    assert client.post(f"{BASE}/content/{item.id}/schedule", json={}, headers=ws["mkt_h"]).status_code == 403
    r = client.post(f"{BASE}/content/{item.id}/schedule", json={}, headers=ws["manager_h"])
    assert r.status_code == 200 and r.json()["status"] == "scheduled"
    info = client.get(f"{BASE}/content/{item.id}/publishing", headers=ws["mkt_h"]).json()
    assert info["status"] == "scheduled" and info["attempts"][0]["status"] == "scheduled"


# ── Publishing ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_post_is_published_once_with_caption_hashtags_and_first_comment(db, ws):  # noqa: F811
    item = _approved(db, ws)
    attempt = pub.schedule(db, ws["tenant"], item.id, datetime.now(timezone.utc), ws["owner"].id)
    db.commit()
    fake = FakePublisher()
    _run(db, attempt, fake)
    assert attempt.status == "published" and attempt.media_ids == ["m-c1"] and attempt.permalink.endswith("/m-c1/")
    container = fake.calls[0]
    assert container[2] == "Coorg, slowly.\n\n#coorg"
    assert ("comment", "m-c1", "Where next?") in fake.calls
    assert db.get(MarketingContent, item.id).status == "published"
    assert db.query(AuditEvent).filter_by(tenant_id=ws["tenant"].id, action="marketing.content.published").count() == 1

    again = FakePublisher()
    _run(db, attempt, again)                                    # re-delivered job
    assert again.calls == []


def test_what_is_posted_is_the_rendered_jpeg_with_the_text_on_it(db, ws, _fake_storage):  # noqa: F811
    tid = ws["tenant"].id
    a = _jpeg(db, tid)
    item = _approved(db, ws, kind="carousel", payload={
        "caption": "Route", "design": {"style": "panel", "colour": "#224466"},
        "slides": [{"headline": "Day 1: Coorg", "body": "Coffee estates", "media": {"asset_id": a.id}},
                   {"headline": "Day 2: Kabini", "media": {"asset_id": a.id}}]})
    att = pub.schedule(db, ws["tenant"], item.id, datetime.now(timezone.utc), ws["owner"].id)
    db.commit()
    fake = FakePublisher()
    _run(db, att, fake)
    assert att.status == "published"
    derived = db.query(MediaAsset).filter_by(tenant_id=tid, status="derived").all()
    assert len(derived) == 2 and {d.provenance["headline"] for d in derived} == {"Day 1: Coorg", "Day 2: Kabini"}
    assert all(d.mime_type == "image/jpeg" and (d.width, d.height) == (1080, 1350) for d in derived)
    urls = [c[1] for c in fake.calls if c[0] == "container"]
    assert urls == [f"https://cdn/{d.id}.jpg" for d in sorted(derived, key=lambda d: d.provenance["headline"])]
    assert a.id not in "".join(urls)                            # never the raw library photo
    data, mime = _fake_storage[0]
    img = Image.open(io.BytesIO(data))
    assert mime == "image/jpeg" and img.format == "JPEG" and img.getpixel((540, 1300)) != img.getpixel((540, 100))


def test_carousel_and_story_shapes(db, ws):  # noqa: F811
    tid = ws["tenant"].id
    a, b = _jpeg(db, tid), _jpeg(db, tid)
    car = _approved(db, ws, kind="carousel", payload={"caption": "Route", "slides": [{"media": {"asset_id": a.id}}, {"media": {"asset_id": b.id}}]})
    att = pub.schedule(db, ws["tenant"], car.id, datetime.now(timezone.utc), ws["owner"].id)
    db.commit()
    fake = FakePublisher()
    _run(db, att, fake)
    assert [c[0] for c in fake.calls] == ["container", "container", "carousel", "publish"] and fake.calls[0][3] is True
    story = _approved(db, ws, kind="story", payload={"frames": [{"media": {"asset_id": a.id}},
                                                               {"media": {"asset_id": b.id}, "sticker": {"type": "question", "text": "Where?"}}]})
    att2 = pub.schedule(db, ws["tenant"], story.id, datetime.now(timezone.utc), ws["owner"].id)
    db.commit()
    fake2 = FakePublisher()
    _run(db, att2, fake2)
    assert att2.media_ids == ["m-c1", "m-c2"] and all(c[4] for c in fake2.calls if c[0] == "container")
    assert "stickers" in att2.error                             # published, with a note that stickers need the app


def test_retry_never_double_posts_a_container_instagram_already_published(db, ws):  # noqa: F811
    item = _approved(db, ws)
    attempt = pub.schedule(db, ws["tenant"], item.id, datetime.now(timezone.utc), ws["owner"].id)
    attempt.container_ids = ["c9"]                               # a previous try created it, then crashed
    db.commit()
    fake = FakePublisher(status={"c9": "PUBLISHED"})
    _run(db, attempt, fake)
    assert attempt.status == "failed" and "already posted" in attempt.error
    assert not [c for c in fake.calls if c[0] == "publish"]


def test_transient_errors_back_off_then_fail_and_return_to_approved(db, ws):  # noqa: F811
    item = _approved(db, ws)
    attempt = pub.schedule(db, ws["tenant"], item.id, datetime.now(timezone.utc), ws["owner"].id)
    db.commit()
    boom = PublishError("Instagram 503", transient=True)
    for n in range(1, pub.MAX_TRIES):
        _run(db, attempt, FakePublisher(fail={"container": boom}))
        assert attempt.status == "scheduled" and attempt.tries == n and _aware(attempt.scheduled_for) > datetime.now(timezone.utc)
        _due(db, attempt)
    _run(db, attempt, FakePublisher(fail={"container": boom}))
    assert attempt.status == "failed" and db.get(MarketingContent, item.id).status == "approved"


def test_quota_used_up_reschedules(db, ws):  # noqa: F811
    item = _approved(db, ws)
    attempt = pub.schedule(db, ws["tenant"], item.id, datetime.now(timezone.utc), ws["owner"].id)
    db.commit()
    _run(db, attempt, FakePublisher(quota=0))
    assert attempt.status == "scheduled" and "limit" in attempt.error


def test_edit_after_scheduling_cancels_and_nothing_is_posted(db, ws):  # noqa: F811
    item = _approved(db, ws)
    attempt = pub.schedule(db, ws["tenant"], item.id, datetime.now(timezone.utc), ws["owner"].id)
    db.commit()
    svc.add_version(db, ws["tenant"].id, item.id, {"caption": "changed"}, origin="human", actor_id=ws["mkt"].id)
    db.commit()
    db.refresh(attempt)
    assert attempt.status == "cancelled" and db.get(MarketingContent, item.id).status == "draft"
    fake = FakePublisher()
    _run(db, attempt, fake)
    assert fake.calls == []


def test_paused_agency_posts_nothing(db, ws):  # noqa: F811
    item = _approved(db, ws)
    attempt = pub.schedule(db, ws["tenant"], item.id, datetime.now(timezone.utc), ws["owner"].id)
    agency.update_agency(db, ws["tenant"], ws["owner"].id, paused=True)
    db.commit()
    fake = FakePublisher()
    _run(db, attempt, fake)
    assert fake.calls == [] and attempt.status == "scheduled" and "paused" in attempt.error and attempt.tries == 0


def test_autopilot_schedules_on_approval_and_suggest_does_not(db, ws):  # noqa: F811
    item = _approved(db, ws)
    assert pub.on_approved(db, ws["tenant"], item.id) is None              # default: suggest
    agency.update_agency(db, ws["tenant"], ws["owner"].id, roles={"publish": "autopilot"})
    db.commit()
    att = pub.on_approved(db, ws["tenant"], item.id)
    assert att is not None and att.status == "scheduled" and _aware(att.scheduled_for) > datetime.now(timezone.utc)


def test_only_one_worker_can_claim_an_attempt(db, ws):  # noqa: F811
    item = _approved(db, ws)
    attempt = pub.schedule(db, ws["tenant"], item.id, datetime.now(timezone.utc), ws["owner"].id)
    attempt.status = "publishing"
    db.commit()
    fake = FakePublisher()
    _run(db, attempt, fake)
    assert fake.calls == []


# ── Adapter ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_publisher_adapter_calls_graph_instagram_with_header_token():
    seen = []

    def handler(req):
        seen.append((req.method, str(req.url), req.headers.get("authorization")))
        if req.url.path.endswith("/media"):
            return httpx.Response(200, json={"id": "c1"})
        if req.url.path.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "m1"})
        return httpx.Response(200, json={"status_code": "FINISHED"})
    p = Publisher("tok", "178", client=httpx.Client(transport=httpx.MockTransport(handler)))
    cid = p.image_container("https://cdn/x.jpg", caption="hi")
    p.wait_ready(cid)
    assert p.publish(cid) == "m1"
    assert all(u.startswith("https://graph.instagram.com/") and a == "Bearer tok" and "tok" not in u for _, u, a in seen)


@pytest.mark.parametrize("status,body,transient", [(503, {}, True), (400, {"error": {"code": 4}}, True), (400, {"error": {"code": 100}}, False)])
def test_publisher_error_classes(status, body, transient):
    p = Publisher("t", "1", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, json=body))))
    with pytest.raises(PublishError) as exc:
        p.publish("c1")
    assert exc.value.transient is transient


def test_container_error_is_permanent():
    p = Publisher("t", "1", client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"status_code": "ERROR"}))))
    with pytest.raises(PublishError) as exc:
        p.wait_ready("c1")
    assert exc.value.transient is False
