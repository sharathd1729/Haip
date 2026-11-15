"""Instagram toolkit phase 4: competitor posts ranked by multiple over their own account's median, with the hook
formula; only pasted (manual) and Business Discovery (api) posts; fed to the brief and the plan input."""
import uuid

from app.models.marketing import MarketingCompetitor, MarketingCompetitorPost, MarketingResearchBrief
from app.models.tenant import Tenant
from app.models.user import UserRole
from app.services import marketing_ai_service as ai
from app.services import marketing_research_service as research
from tests.conftest import seed_capabilities
from tests.test_marketing_studio_content import BASE, enable_module, make_user, ws  # noqa: F401  (fixture)


def _comp(db, tenant_id, handle, posts):
    c = MarketingCompetitor(tenant_id=tenant_id, handle=handle)
    db.add(c)
    db.flush()
    for i, (source, views, likes, caption) in enumerate(posts):
        db.add(MarketingCompetitorPost(tenant_id=tenant_id, competitor_id=c.id, source=source, views=views, like_count=likes,
                                       comments_count=0 if likes is not None else None, caption=caption,
                                       permalink=f"https://www.instagram.com/p/{handle}{i}/", posted_at=f"2026-11-{10 - i:02d}"))
    db.commit()
    return c


def test_rank_uses_each_accounts_own_median_and_names_the_formula(db, ws):
    tid = ws["tenant"].id
    _comp(db, tid, "hillside", [("manual", 42000, None, "Nobody tells you the hills are best in the rain."),
                                ("manual", 10000, None, "Room tour"), ("manual", 9000, None, "Breakfast"),
                                ("api", None, 120, "Sunset"), ("manual", 11000, None, "Pool")])
    _comp(db, tid, "bigvillas", [("api", None, 900, "Villa"), ("api", None, 1000, "Garden"), ("api", None, 1100, "Lawn"),
                                 ("api", None, 600, "Offer")])
    _comp(db, tid, "scraped", [("collector", 999999, None, "x"), ("apify", 5, None, "y"), ("apify", 5, None, "z")])
    posts = research.ranked(db, tid)["posts"]
    top = posts[0]
    assert top["handle"] == "hillside" and top["metric"] == "views" and top["band"] == "signal"
    assert top["multiple"] == round(42000 / 10500, 2) and top["formula"] == "Nobody Tells You"
    big = [p for p in posts if p["handle"] == "bigvillas"]
    assert all(p["metric"] == "engagement" for p in big) and {p["band"] for p in big} <= {"normal", "below"}
    assert not [p for p in posts if p["handle"] == "scraped"]       # collector copies are never ranked


def test_too_few_posts_gives_no_multiple(db, ws):
    _comp(db, ws["tenant"].id, "tiny", [("manual", 500, None, "a"), ("manual", 50000, None, "b")])
    assert {p["band"] for p in research.ranked(db, ws["tenant"].id)["posts"]} == {"unknown"}


def test_ranked_posts_reach_the_brief_and_the_plan_input(db, ws):
    tid = ws["tenant"].id
    _comp(db, tid, "hillside", [("manual", 42000, None, "Nobody tells you the hills are best in the rain."),
                                ("manual", 10000, None, "Room tour"), ("manual", 9000, None, "Breakfast"),
                                ("manual", 11000, None, "Pool")])
    measured = research.measured(db, tid)
    assert measured["ranked"][0]["band"] == "signal"
    db.add(MarketingResearchBrief(tenant_id=tid, measured=measured, status="ready",
                                  assessment={"summary": "s", "themes": [], "formats": [], "opportunities": [], "avoid": []}))
    db.commit()
    assert "Nobody Tells You" in ai._latest_research(db, tid)


def test_ranked_is_on_the_research_endpoint_per_workspace(client, db, ws):
    _comp(db, ws["tenant"].id, "hillside", [("manual", 30000, None, "Stop booking hill stations in May."),
                                            ("manual", 10000, None, "a"), ("manual", 10000, None, "b")])
    r = client.get(f"{BASE}/research", headers=ws["mkt_h"])
    assert r.status_code == 200 and r.json()["ranked"]["posts"][0]["formula"] == "Negative Command"
    _, foh_h = make_user(db, ws["tenant"].id, UserRole.FOH)
    assert client.get(f"{BASE}/research", headers=foh_h).status_code == 403
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    seed_capabilities(db, other.id)
    enable_module(db, other.id)
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    assert client.get(f"{BASE}/research", headers=other_h).json()["ranked"]["posts"] == []


def test_pasted_post_keeps_its_views(client, db, ws):
    c = _comp(db, ws["tenant"].id, "hillside", [])
    r = client.post(f"{BASE}/research/competitors/{c.id}/posts", headers=ws["mkt_h"],
                    json={"permalink": "https://www.instagram.com/reel/ABC123/", "views": 41000, "media_type": "REELS"})
    assert r.status_code == 201, r.text
    assert db.query(MarketingCompetitorPost).filter_by(competitor_id=c.id).one().views == 41000
