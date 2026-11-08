"""Website phase 6: a page per stay + compare data, Hindi words reviewed and published with the version, and the launch
report (data + PDF; the booking test is a dry run). The AI is faked."""

import copy
from unittest.mock import patch

import pytest

from app.models.user import UserRole
from app.models.website import BookingHold, Site, SiteAiJob
from app.services import website_i18n, website_launch
from app.services import website_spec_service as wspec
from app.services.website_service import WebsiteError
from tests.test_marketing_studio_content import make_user
from tests.test_website_v2_booking import _spec, _v2_live
from tests.website_fixtures import BASE, add_property, make_tenant, wsite  # noqa: F401

PUB = "/api/v1/public/sites"
HI = {
    "tagline": "कॉफ़ी की पहाड़ियों में शांत विला",
    "pages": {"/": {"title": "होम", "seo_title": "हिल विला, कूर्ग"}},
    "sections": {"hero": {"headline": "शांत विला"}},
}


@pytest.fixture(autouse=True)
def _no_rate_limit():
    with patch("app.middleware.rate_limit._check_limit", return_value=(True, 0)):
        yield


def test_every_stay_has_a_page_and_compare_data(client, db, wsite):  # noqa: F811
    add_property(db, wsite["tenant"].id, name="Blue Heron", price=6000)
    host = _v2_live(client, db, wsite, grounded=False)
    boot = client.get(f"{PUB}/{host}/bootstrap").json()
    idx = {s["slug"]: s for s in boot["stays_index"]}
    assert set(idx) == {"green-goose", "blue-heron"} and idx["blue-heron"]["from"] is None  # handoff: no figure
    st = client.get(f"{PUB}/{host}/stays/blue-heron").json()
    assert st["name"] == "Blue Heron" and "from_price" not in st
    wsite["tenant"].brand_config = {**wsite["tenant"].brand_config, "price_disclosure": "grounded"}
    db.commit()
    assert client.get(f"{PUB}/{host}/stays/blue-heron").json()["from_price"] == "6000"
    assert client.get(f"{PUB}/{host}/stays/nope").status_code == 404


def _with_hindi(words):
    spec = _spec()
    spec["i18n"] = {"hi": words}
    return spec


def test_hindi_words_are_validated_like_the_english_ones():
    out = wspec.validate(_with_hindi(HI))
    assert out["i18n"]["hi"]["sections"]["hero"]["headline"] == "शांत विला"
    for bad in (
        {"sections": {"ghost": {"heading": "x"}}},
        {"sections": {"hero": {"media": "asset:x"}}},
        {"sections": {"hero": {"headline": "क" * 91}}},
        {"sections": {"hero": {"subhead": "सिर्फ ₹4,200 प्रति रात"}}},
        {"pages": {"/nope": {"title": "x"}}},
    ):
        with pytest.raises(WebsiteError):
            wspec.validate(_with_hindi(bad))
    with pytest.raises(WebsiteError):
        wspec.validate({**_spec(), "i18n": {"ta": {}}})  # only languages HAIP has are accepted


def test_translate_makes_a_draft_a_person_publishes(client, db, wsite):  # noqa: F811
    host = _v2_live(client, db, wsite)
    assert client.post(f"{BASE}/translate", json={"language": "hi"}, headers=wsite["mkt_h"]).status_code == 403
    with patch("app.workers.tasks.website.translate.delay") as q:
        r = client.post(f"{BASE}/translate", json={"language": "hi"}, headers=wsite["owner_h"])
    assert r.status_code == 202 and q.call_count == 1
    job = db.get(SiteAiJob, r.json()["id"])

    def fake(task, tenant_id, system, user, tool):
        import json

        wanted = json.loads(user.split("INPUT: ", 1)[1])
        items = [
            {
                "key": w["key"],
                "text": "क" * (w["max"] + 5) if w["key"].endswith(":subhead") else "हिंदी " + w["key"][-6:],
            }
            for w in wanted
        ]
        return {"items": items}, {"model": "fake"}, "gemini"

    with patch("app.services.marketing_ai_service._call", side_effect=fake):
        website_i18n.run(db, job, db.query(Site).filter_by(tenant_id=wsite["tenant"].id).one())
    db.commit()
    assert job.status == "ready" and job.result_version_id
    draft = client.get(f"{BASE}/draft", headers=wsite["owner_h"]).json()
    assert "hi" in draft["doc"]["i18n"] and "hi" not in (
        client.get(f"{PUB}/{host}/bootstrap").json()["doc"].get("i18n") or {}
    )
    vid = draft["version"]["id"]
    with patch("app.workers.tasks.website.revalidate.delay"):
        assert (
            client.post(
                f"{BASE}/versions/{vid}/publish", json={"version_id": vid}, headers=wsite["owner_h"]
            ).status_code
            == 200
        )
    live = client.get(f"{PUB}/{host}/bootstrap").json()["doc"]["i18n"]["hi"]
    assert live["sections"]["hero"]["headline"].startswith("हिंदी")
    assert client.get(f"{BASE}/languages", headers=wsite["mkt_h"]).json() == [
        {"code": "hi", "name": "हिन्दी", "live": True}
    ]
    other = make_tenant(db, "Elsewhere")
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    assert client.get(f"{BASE}/translate/{job.id}", headers=other_h).status_code == 404


def test_a_retried_translation_only_asks_for_the_pages_still_missing(client, db, wsite):  # noqa: F811
    from app.services.marketing_ai_service import LLMTransientError

    _v2_live(client, db, wsite)
    spec = _spec()
    spec["pages"].append({"slug": "/about", "title": "About", "sections": [
        {"id": "story", "type": "text", "variant": "plain", "slots": {"heading": "Our story", "body": "Two villas."}},
        {"id": "contact2", "type": "contact", "variant": "split"}]})
    site = db.query(Site).filter_by(tenant_id=wsite["tenant"].id).one()
    head, _ = wspec.create_draft(db, site, spec, actor_id=wsite["owner"].id)
    job = SiteAiJob(tenant_id=site.tenant_id, site_id=site.id, kind="translate", request="hi", status="running",
                    base_version_id=head.id)
    db.add(job)
    db.commit()
    asked = []

    def fake(task, tenant_id, system, user, tool):
        import json

        wanted = json.loads(user.split("INPUT: ", 1)[1])
        asked.append(wanted[0]["key"])
        if any(w["key"].startswith("page:/about") for w in wanted) and len(asked) == 2:
            raise LLMTransientError("busy")              # the second page fails once
        return {"items": [{"key": w["key"], "text": "हिंदी"} for w in wanted]}, {"model": "fake"}, "gemini"

    with patch("app.services.marketing_ai_service._call", side_effect=fake):
        with pytest.raises(LLMTransientError):
            website_i18n.run(db, job, site)
        db.refresh(job)                                  # the finished page was saved (a rollback on SQLite would drop the fixtures)
        assert job.result["partial"]["pages"] == ["/"]
        website_i18n.run(db, job, site)
    assert asked == ["page:/:title", "page:/about:title", "page:/about:title"]   # "/" was translated (and paid) once
    assert job.status == "ready"
    hi = db.get(type(head), job.result_version_id).doc["i18n"]["hi"]["sections"]
    assert {"hero", "story"} <= set(hi)                                          # both pages kept in the draft


def test_merge_keeps_english_for_missing_or_too_long():
    loc: dict = {}
    wanted = [
        {"key": "sec:hero:headline", "text": "Hi", "max": 10},
        {"key": "page:/:title", "text": "Home", "max": 5},
        {"key": "sec:hero:subhead", "text": "x", "max": 3},
    ]
    left = website_i18n.merge(
        loc,
        wanted,
        website_i18n.TranslateOut(
            items=[
                {"key": "sec:hero:headline", "text": "नमस्ते"},
                {"key": "page:/:title", "text": "होम"},
                {"key": "sec:hero:subhead", "text": "बहुत लंबा"},
                {"key": "evil:key", "text": "x"},
            ]
        ),
    )
    assert loc == {"sections": {"hero": {"headline": "नमस्ते"}}, "pages": {"/": {"title": "होम"}}} and left == [
        "sec:hero:subhead"
    ]


def test_launch_report_and_pdf(client, db, wsite):  # noqa: F811
    host = _v2_live(client, db, wsite, grounded=True)
    rep = client.get(f"{BASE}/launch-report", headers=wsite["mkt_h"]).json()
    assert rep["site"]["url"] == f"https://{host}" and rep["pages"][0]["path"] == "/"
    assert set(rep["quality"]["scores"]) == {"performance", "accessibility", "seo"}
    assert rep["schema"]["/"][0] in ("VacationRental", "LodgingBusiness")
    assert rep["booking"]["dry_run"][0]["ok"] and "8,400" in rep["booking"]["dry_run"][0]["result"]
    assert db.query(BookingHold).count() == 0  # the booking test books nothing
    pdf = client.get(f"{BASE}/launch-report.pdf", headers=wsite["owner_h"])
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    other = make_tenant(db, "Elsewhere")
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    assert client.get(f"{BASE}/launch-report", headers=other_h).status_code == 404


def test_launch_report_before_publishing_says_so(db, wsite):  # noqa: F811
    site = db.query(Site).filter_by(tenant_id=wsite["tenant"].id).one()
    rep = website_launch.build(db, wsite["tenant"], site)
    assert "isn't published" in rep["problem"] and website_launch.render(rep)[:4] == b"%PDF"


def test_hindi_text_never_breaks_the_pdf(db, wsite):  # noqa: F811
    rep = {
        "site": {"name": "हिल विला", "status": "live", "url": "https://x"},
        "content": {"guides_live": 0, "reviews_shown": 0, "promo_codes_on": 0, "languages": ["English", "Hindi"]},
    }
    assert website_launch.render(copy.deepcopy(rep))[:4] == b"%PDF"
