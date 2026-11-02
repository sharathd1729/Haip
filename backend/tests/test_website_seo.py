"""Website phase 3: JSON-LD per page (business type, honest ratings, consented reviews, offers only when prices show,
FAQPage) and the publish gate's speed / accessibility / search scores (warn; only failing contrast blocks)."""
from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from app.models.marketing import MarketingGuestReview
from app.services import website_quality, website_seo
from tests.test_website_v2_booking import _spec, _v2_live
from tests.website_fixtures import BASE, wsite  # noqa: F401

PUB = "/api/v1/public/sites"


@pytest.fixture(autouse=True)
def _no_rate_limit():
    with patch("app.middleware.rate_limit._check_limit", return_value=(True, 0)):
        yield


@pytest.mark.parametrize("bt,kind,schema", [
    ("villa_resort", "villa", "VacationRental"), ("homestay", "homestay", "VacationRental"), ("hotel", "boutique_hotel", "Hotel"),
    ("Beach Resort", "resort", "Resort"), ("caravan", "caravan", "LodgingBusiness"),
    ("Serviced apartments", "service_apartments", "LodgingBusiness"), ("travel agency", "travel_agency", "TravelAgency"),
    (None, None, "LodgingBusiness"),
])
def test_business_kind_and_schema_type(bt, kind, schema):
    assert website_seo.business_kind(bt) == kind and website_seo.schema_type(bt) == schema


def _review(db, tid, rating, consent=True, comment="Lovely stay, the cook was wonderful."):
    db.add(MarketingGuestReview(tenant_id=tid, source="google", external_id=f"r{rating}{consent}", reviewer="Priya Sharma",
                                rating=rating, comment=comment, reviewed_at="2026-10-01",
                                consent_at=datetime(2026, 10, 2, tzinfo=UTC) if consent else None))
    db.commit()


def test_live_jsonld_ratings_reviews_offers(client, db, wsite):  # noqa: F811
    t = wsite["tenant"]
    t.business_type = "villa_resort"
    _review(db, t.id, 5)
    _review(db, t.id, 2, consent=False)          # counted in the average, never shown
    spec = _spec()
    spec["pages"][0]["sections"].insert(1, {"id": "rev", "type": "reviews", "variant": "quote-carousel"})
    with patch("tests.test_website_v2_booking._spec", return_value=spec):
        host = _v2_live(client, db, wsite, grounded=True)
    boot = client.get(f"{PUB}/{host}/bootstrap").json()
    biz = boot["jsonld"]["/"][0]
    assert biz["@type"] == "VacationRental" and biz["url"] == f"https://{host}/"
    assert biz["aggregateRating"]["reviewCount"] == 2 and biz["aggregateRating"]["ratingValue"] == 3.5
    assert [r["author"]["name"] for r in biz["review"]] == ["Priya"]      # consented only, first name
    assert biz["makesOffer"][0]["price"] == "4200" and biz["priceRange"].startswith("From ₹4,200")
    assert boot["business_kind"] == "villa"


def test_handoff_jsonld_has_no_price(client, db, wsite):  # noqa: F811
    host = _v2_live(client, db, wsite, grounded=False)
    biz = client.get(f"{PUB}/{host}/bootstrap").json()["jsonld"]["/"][0]
    assert "makesOffer" not in biz and "priceRange" not in biz and "₹" not in str(biz)


def test_preview_has_no_jsonld(client, db, wsite):  # noqa: F811
    _v2_live(client, db, wsite)
    link = client.get(f"{BASE}/preview-link", headers=wsite["owner_h"]).json()["url"]
    token = link.split("/_haip/preview/", 1)[1]
    boot = client.get(f"/api/v1/public/preview/{token}/bootstrap")
    assert boot.status_code == 200 and boot.json()["jsonld"] == {} and boot.json()["tracking"] == {}


def test_publish_checklist_has_scores_and_contrast_blocks():
    doc = {"site": {"name": "X", "contact": {"phone": "1", "address": "Coorg"}},
           "tokens": {"palette": {"name": "custom", "ink": "#777777", "surface": "#888888", "primary": "#2F5D46", "accent": "#A8641C"}},
           "pages": [{"slug": "/", "title": "Home", "seo": {"title": "Hill Villas in Coorg", "description": "x" * 80},
                      "sections": [{"id": "hero", "type": "hero", "slots": {"headline": "Hi"}}]}]}
    q = website_quality.audit(doc, {}, {"a1": {"alt": "", "w": None, "h": None}})
    contrast = next(i for i in q["items"] if i["key"] == "contrast")
    assert contrast["level"] == "block" and not contrast["ok"]
    assert all(i["level"] in ("ok", "warn") for i in q["items"] if i["key"] != "contrast")
    assert set(q["scores"]) == {"performance", "accessibility", "seo"} and q["scores"]["accessibility"] < 100


def test_v2_draft_checklist_lists_scores(client, db, wsite):  # noqa: F811
    r = client.post(f"{BASE}/draft/v2", json={"spec": _spec()}, headers=wsite["owner_h"])
    keys = {c["key"]: c for c in r.json()["checks"]}
    assert {"score_performance", "score_accessibility", "score_seo"} <= set(keys)
    assert all(keys[k]["level"] in ("ok", "warn") for k in keys if k.startswith("score_"))
