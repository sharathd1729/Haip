"""Link-in-bio "Packages" (the itinerary funnel): published retail packages only (never b2b), day titles from the published
itinerary, a wa.me link naming the package that the concierge's match_package recognises, prices only in grounded mode."""
from urllib.parse import unquote

from app.models.business_record import BusinessRecord
from app.services import agent_bench, bio_packages, sales_gateway

DOC = {"site": {"contact": {"whatsapp": "+91 98450 00000"}}}


def test_published_retail_packages_with_day_plans_and_a_whatsapp_enquiry(db):
    world = agent_bench.build_world(db, playbook=False)
    rows = bio_packages.items(db, world.tenant, DOC)
    keys = [r["key"] for r in rows]
    assert "rathaa-base-b2b" not in keys and "mysuru-coorg" in keys          # partner-only never shown
    coorg = next(r for r in rows if r["key"] == "mysuru-coorg")
    assert coorg["days"] and coorg["price"] is None                          # handoff mode: no price
    assert coorg["whatsapp_url"].startswith("https://wa.me/919845000000?text=")
    text = unquote(coorg["whatsapp_url"].split("text=", 1)[1])
    assert text == "Hi! I'd like to know more about Mysuru and Coorg (3 days)."
    # The prefilled message ties the enquiry to THAT package.
    assert sales_gateway.match_package(db, world.tenant.id, {"questions": [text]}) == "mysuru-coorg"
    assert next(r for r in rows if r["key"] == "mysuru-escape")["length"] == "Day trip"


def test_prices_only_when_the_workspace_publishes_prices(db):
    world = agent_bench.build_world(db, playbook=False)
    world.tenant.brand_config = {"price_disclosure": "grounded"}
    db.commit()
    rows = {r["key"]: r for r in bio_packages.items(db, world.tenant, DOC)}
    assert rows["mysuru-coorg"]["price"] == "From Rs 65,000 + GST"
    assert bio_packages._inr(125000) == "1,25,000"


def test_drafts_and_other_workspaces_never_appear(db):
    world = agent_bench.build_world(db, playbook=False)
    other = agent_bench.build_world(db, playbook=False)
    db.query(BusinessRecord).filter_by(tenant_id=other.tenant.id).delete()
    db.commit()
    assert bio_packages.items(db, other.tenant, DOC) == []
    assert bio_packages.items(db, world.tenant, None)[0]["whatsapp_url"] is None      # no number known: no link


def test_public_links_page_is_still_404_for_an_unknown_site(client):
    assert client.get("/api/v1/public/sites/nobody.genhaip.site/links").status_code == 404
