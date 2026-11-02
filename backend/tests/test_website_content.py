"""Website phase 5: guides (Studio "article" items, approved versions only on the site, never posted to social), Google
reviews shown only with recorded consent, photo/Canva imports into the library, and the video hero variant.
The AI is faked; nothing leaves HAIP."""

import io
from unittest.mock import patch

import pytest
from PIL import Image

from app.core.cache import ctx_bust
from app.models.audit_event import AuditEvent
from app.models.marketing import MarketingContent, MarketingGuestReview
from app.models.media_asset import MediaAsset
from app.models.user import UserRole
from app.services import marketing_content_service as content_svc
from app.services import marketing_publish_service as publish
from app.services import website_blog
from app.services.marketing_content_service import MarketingError
from tests.test_marketing_studio_content import enable_module, make_user
from tests.test_website_v2_booking import _spec, _v2_live
from tests.website_fixtures import BASE, make_tenant, wsite  # noqa: F401

PUB = "/api/v1/public/sites"
BODY = (
    "## Getting there\n\nThe drive from Bengaluru takes most of a morning, so leave early and stop for breakfast on "
    "the way.\n\n## What to pack\n\nWarm layers for the evenings, walking shoes and a rain jacket in the monsoon. "
    "Children love the coffee estate walk, so bring a hat and water for everyone in the group."
)
ARTICLE = {
    "title": "A weekend in Coorg with kids",
    "excerpt": "How to plan two easy days in the coffee hills with children.",
    "body": BODY,
    "seo_description": "Plan two easy days in Coorg with children: getting there, packing, what to do.",
}


@pytest.fixture(autouse=True)
def _no_rate_limit():
    with patch("app.middleware.rate_limit._check_limit", return_value=(True, 0)):
        yield


def _written(client, db, w, topic="A weekend in Coorg with kids"):
    with patch("app.workers.tasks.website.blog_draft.delay") as q:
        r = client.post(f"{BASE}/blog", json={"topic": topic}, headers=w["mkt_h"])
    assert r.status_code == 202 and q.call_count == 1
    with patch("app.services.marketing_ai_service._call", return_value=(ARTICLE, {"model": "fake"}, "gemini")):
        website_blog.run_draft(db, w["tenant"], r.json()["id"], topic)
    db.commit()
    return client.get(f"{BASE}/blog", headers=w["mkt_h"]).json()[0]


def test_guide_goes_live_only_when_approved(client, db, wsite):  # noqa: F811
    host = _v2_live(client, db, wsite)
    g = _written(client, db, wsite)
    assert g["payload"]["slug"] == "a-weekend-in-coorg-with-kids" and g["status"] == "draft" and not g["live"]
    assert client.get(f"{PUB}/{host}/blog").json()["items"] == []  # a draft is never on the site
    seen = {"version_id": g["version_id"]}
    sub = client.post(f"{BASE}/blog/{g['id']}/submit", json=seen, headers=wsite["mkt_h"])
    assert sub.status_code == 200, sub.text
    assert (
        client.post(f"{BASE}/blog/{g['id']}/approve", json=seen, headers=wsite["mkt_h"]).status_code == 403
    )  # wrong role
    with patch("app.workers.tasks.website.revalidate.delay"):
        r = client.post(f"{BASE}/blog/{g['id']}/approve", json=seen, headers=wsite["manager_h"])
    assert r.status_code == 200 and r.json()["live"]
    items = client.get(f"{PUB}/{host}/blog").json()["items"]
    assert [i["slug"] for i in items] == ["a-weekend-in-coorg-with-kids"]
    art = client.get(f"{PUB}/{host}/blog/a-weekend-in-coorg-with-kids").json()
    assert art["title"] == ARTICLE["title"] and "## What to pack" in art["body"]
    assert client.get(f"{PUB}/{host}/bootstrap").json()["blog_count"] == 1
    # an edit takes it down until approved again (same rule as every Studio item)
    with patch("app.workers.tasks.website.revalidate.delay"):
        client.put(
            f"{BASE}/blog/{g['id']}",
            json={"payload": {**ARTICLE, "slug": "a-weekend-in-coorg-with-kids", "title": "Coorg with kids"}},
            headers=wsite["mkt_h"],
        )
    assert client.get(f"{PUB}/{host}/blog").json()["items"] == []
    assert client.get(f"{PUB}/{host}/blog/a-weekend-in-coorg-with-kids").status_code == 404


def test_guides_are_per_workspace_and_never_posted_to_social(client, db, wsite):  # noqa: F811
    enable_module(db, wsite["tenant"].id)  # Studio on, so its generate endpoint answers below
    ctx_bust(wsite["tenant"].id)
    _v2_live(client, db, wsite)
    g = _written(client, db, wsite)
    other = make_tenant(db, "Elsewhere")
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    assert client.get(f"{BASE}/blog", headers=other_h).json() == []
    assert (
        client.post(f"{BASE}/blog/{g['id']}/archive", json={"version_id": g["version_id"]}, headers=other_h).status_code
        == 404
    )
    with pytest.raises(MarketingError) as e:
        publish.schedule_all(db, wsite["tenant"], g["id"], None, wsite["owner"].id)
    assert e.value.code == "website_only"
    # Studio's Instagram copywriter never rewrites a guide (website_blog writes them)
    r = client.post(f"/api/v1/marketing/studio/content/{g['id']}/generate", json={}, headers=wsite["mkt_h"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "website_only", r.text


def test_guide_date_is_the_business_day_not_utc(client, db, wsite):  # noqa: F811
    from datetime import UTC, datetime

    _v2_live(client, db, wsite)
    g = _written(client, db, wsite)
    seen = {"version_id": g["version_id"]}
    client.post(f"{BASE}/blog/{g['id']}/submit", json=seen, headers=wsite["mkt_h"])
    with patch("app.workers.tasks.website.revalidate.delay"):
        client.post(f"{BASE}/blog/{g['id']}/approve", json=seen, headers=wsite["manager_h"])
    item = db.get(MarketingContent, g["id"])
    item.updated_at = datetime(2026, 11, 2, 22, 30, tzinfo=UTC)  # 04:00 IST on 3 Nov
    db.commit()
    assert website_blog.listing(db, wsite["tenant"].id)[0]["date"] == "2026-11-03"
    assert website_blog.article(db, wsite["tenant"].id, g["payload"]["slug"])["date"] == "2026-11-03"


def test_guide_text_follows_the_price_policy(db, wsite):  # noqa: F811
    item = content_svc.create_item(db, wsite["tenant"].id, kind="article", title="Prices", actor_id=wsite["owner"].id)
    with pytest.raises(MarketingError):  # handoff (default): no rupee figures in anything a guest reads
        content_svc.add_version(
            db,
            wsite["tenant"].id,
            item.id,
            {**ARTICLE, "slug": "prices", "body": BODY + "\n\nA night costs Rs 12,000."},
            origin="human",
            actor_id=wsite["owner"].id,
        )


def test_bad_ai_output_is_refused_not_stored(client, db, wsite):  # noqa: F811
    with patch("app.workers.tasks.website.blog_draft.delay"):
        gid = client.post(f"{BASE}/blog", json={"topic": "Monsoon drives"}, headers=wsite["owner_h"]).json()["id"]
    with patch(
        "app.services.marketing_ai_service._call", return_value=({**ARTICLE, "body": "Too short."}, {}, "gemini")
    ):
        with pytest.raises(MarketingError):  # the task marks the guide failed (website.blog_draft)
            website_blog.run_draft(db, wsite["tenant"], gid, "Monsoon drives")
    assert db.get(MarketingContent, gid).current_version_id is None


def _review(db, tid, rating=5):
    r = MarketingGuestReview(
        tenant_id=tid,
        source="google",
        external_id=f"g{rating}",
        reviewer="Kavya Iyer",
        rating=rating,
        comment="Wonderful hosts, spotless rooms and the best filter coffee.",
        reviewed_at="2026-09-12",
    )
    db.add(r)
    db.commit()
    return r


def test_review_shows_only_after_recorded_consent(client, db, wsite):  # noqa: F811
    spec = _spec()
    spec["pages"][0]["sections"].insert(1, {"id": "rev", "type": "reviews", "variant": "grid"})
    with patch("tests.test_website_v2_booking._spec", return_value=spec):
        host = _v2_live(client, db, wsite)
    r = _review(db, wsite["tenant"].id)
    assert client.get(f"{PUB}/{host}/bootstrap").json()["bound"]["rev"]["items"] == []
    url = f"{BASE}/reviews/{r.id}/consent"
    assert client.put(url, json={"note": "Asked on WhatsApp"}, headers=wsite["mkt_h"]).status_code == 403
    with patch("app.workers.tasks.website.revalidate.delay"):
        out = client.put(url, json={"note": "Asked on WhatsApp, said yes"}, headers=wsite["owner_h"]).json()
    assert out[0]["shown"] is True
    items = client.get(f"{PUB}/{host}/bootstrap").json()["bound"]["rev"]["items"]
    assert items[0]["name"] == "Kavya" and items[0]["source"] == "google"
    with patch("app.workers.tasks.website.revalidate.delay"):
        client.put(url, json={"note": None}, headers=wsite["owner_h"])
    assert client.get(f"{PUB}/{host}/bootstrap").json()["bound"]["rev"]["items"] == []
    acts = {a.action for a in db.query(AuditEvent).filter_by(tenant_id=wsite["tenant"].id)}
    assert {"website.review_consent_recorded", "website.review_consent_withdrawn"} <= acts
    other = make_tenant(db, "Elsewhere")
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    assert client.put(url, json={"note": "x y z"}, headers=other_h).status_code == 404


def test_import_reviews_needs_google(client, db, wsite):  # noqa: F811
    assert client.post(f"{BASE}/reviews/import", headers=wsite["owner_h"]).status_code == 409


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (40, 90, 70)).save(buf, "PNG")
    return buf.getvalue()


def test_canva_png_import_lands_in_the_library(client, db, wsite):  # noqa: F811
    with (
        patch("app.services.media_storage.upload_marketing_media", return_value="k", create=True),
        patch("app.api.v1.endpoints.website_growth.Session", create=True),
    ):
        r = client.post(
            f"{BASE}/media/import",
            files={"file": ("design.png", _png(), "image/png")},
            data={"origin": "canva", "alt_text": "Monsoon offer"},
            headers=wsite["mkt_h"],
        )
    assert r.status_code == 201, r.text
    a = db.get(MediaAsset, r.json()["id"])
    assert a.provenance.get("canva_export") is True and a.mime_type.startswith("image/")
    assert db.query(AuditEvent).filter_by(tenant_id=wsite["tenant"].id, action="website.media_imported").count() == 1
    assert (
        client.post(
            f"{BASE}/media/import", files={"file": ("x.png", _png(), "image/png")}, headers=wsite["foh_h"]
        ).status_code
        == 403
    )


def test_video_hero_spec_keeps_a_library_video(client, db, wsite):  # noqa: F811
    v = MediaAsset(
        tenant_id=wsite["tenant"].id,
        source="upload",
        storage_key="t/clip.mp4",
        mime_type="video/mp4",
        bytes=1000,
        sha256="0" * 64,
        width=1280,
        height=720,
        status="active",
        alt_text="Drive at dawn",
        duration_ms=8000,
    )
    db.add(v)
    db.commit()
    spec = _spec()
    spec["pages"][0]["sections"][0] = {
        "id": "hero",
        "type": "hero",
        "variant": "video",
        "slots": {"headline": "Quiet villas", "video": f"asset:{v.id}"},
    }
    with patch("tests.test_website_v2_booking._spec", return_value=spec):
        host = _v2_live(client, db, wsite)
    boot = client.get(f"{PUB}/{host}/bootstrap").json()
    assert boot["doc"]["pages"][0]["sections"][0]["slots"]["video"] == f"asset:{v.id}" and v.id in boot["assets"]
