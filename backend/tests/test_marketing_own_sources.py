"""Marketing Studio reads the business's own approved data (24 Oct 2026): the knowledge base (only entries retrieval may
use), the EFFECTIVE published business records (never drafts or superseded versions) and Meta ad copy, prices
stripped. Shared by brand voice (marketing_brand_dna.sources) and every step fed by marketing_ai_service._facts."""
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from app.models.ad_entity import AdEntity
from app.models.knowledge import KnowledgeEntry
from app.services import business_data_service as bds
from app.services import marketing_ai_service as ai
from app.services import marketing_brand_dna as dna
from app.services import marketing_content_service as svc
from app.services import marketing_lint
from tests.test_business_data import _workspace, coorg, package
from tests.test_package_pricing import publish, rates


def _kb(db, tid, content, **over):
    fields = {"is_active": True, "review_status": "approved", "embedding_status": "done", **over}
    e = KnowledgeEntry(id=str(uuid.uuid4()), tenant_id=tid, category="faq", content=content, **fields)
    db.add(e)
    db.commit()
    return e


def _ad(db, tid, name, creative, status="ACTIVE"):
    db.add(AdEntity(tenant_id=tid, ad_account_id="act_1", level="ad", entity_id=uuid.uuid4().hex[:12], name=name,
                    effective_status=status, creative=creative))
    db.commit()


def _business(db):
    w = _workspace(db)
    publish(db, w, "coorg", coorg(), kind="destination")
    publish(db, w, "coorg-signature", package(name="Old name", destination_keys=["coorg"], rates=[rates()]))
    publish(db, w, "coorg-signature", package(destination_keys=["coorg"], rates=[rates()],      # supersedes "Old name"
                                              summary="Pets welcome on request. From Rs 18,000 per night."))
    bds.create_draft(db, w.t.id, "package", "secret", package(name="Draft only", rates=[rates()]), w.owner.id)
    publish(db, w, None, {"advance_percent": 30, "balance_due_days_before_checkin": 7, "confirmed_by_ratha": True},
            kind="payment_policy")
    publish(db, w, None, {"check_in_time": "14:00", "check_out_time": "11:00", "house_rules": ["No smoking inside"]},
            kind="stay_rules")
    tid = w.t.id
    _kb(db, tid, "Two double beds and an attached bathroom with hot shower.", question="Sleeping?")
    _kb(db, tid, "Our chef cooks breakfast; rate 2500 per night.")
    _kb(db, tid, "PENDING-REVIEW text", review_status="pending")
    _kb(db, tid, "STALE text", stale_since=datetime.now(timezone.utc))
    _kb(db, tid, "INACTIVE text", is_active=False)
    _kb(db, tid, "NOT-INDEXED text", embedding_status="pending")
    _ad(db, tid, "INTERNAL-AD-NAME", {"title": "Slow trips through Coorg", "body": "Book now from ₹9,999"})
    _ad(db, tid, "paused one", {"title": "Older paused ad", "body": ""}, status="PAUSED")
    return w


def test_brand_voice_reads_usable_kb_effective_records_and_ad_copy_without_prices(db):
    w = _business(db)
    other = _workspace(db)                                    # another tenant's data never leaks in
    _kb(db, other.t.id, "OTHER-TENANT kb")
    _ad(db, other.t.id, "x", {"title": "OTHER-TENANT ad"})
    publish(db, other, "other-pkg", package(name="OTHER-TENANT package", rates=[rates()]))

    src = dna.sources(db, w.t)
    text = str(src)
    assert any("attached bathroom" in k for k in src["knowledge"]) and any("chef cooks" in k for k in src["knowledge"])
    for hidden in ("PENDING-REVIEW", "STALE", "INACTIVE", "NOT-INDEXED", "OTHER-TENANT", "Draft only", "Old name",
                   "INTERNAL-AD-NAME"):
        assert hidden not in text, hidden
    pkg = src["business_data"]["packages"]
    assert [p["name"] for p in pkg] == ["Signature Caravan - Coorg"] and "Bed linen" in pkg[0]["inclusions"]
    assert src["business_data"]["stay_rules"]["house_rules"] == ["No smoking inside"]
    assert "payment_policy" not in src["business_data"]                       # handoff: no payment terms
    assert src["ads"][0].startswith("Slow trips through Coorg") and len(src["ads"]) == 2
    for price in ("18,000", "18000", "9,999", "2500", "rates"):
        assert price not in text, price
    assert dna.source_counts(src) | {"website_chars": 0} == {
        "website_chars": 0, "captions": 0, "properties": 0, "knowledge": 2, "packages": 1, "destinations": 1,
        "itineraries": 0, "policies": 1, "ads": 2}


def test_brand_voice_draft_sends_own_sources_and_records_counts(db):
    w = _business(db)
    seen = {}

    def fake(task, tenant_id, system, user, tool):
        seen.update(system=system, user=user)
        return {"tone": "Unhurried", "gaps": []}, {"model": "m"}, "gemini"
    with patch.object(ai, "_call", side_effect=fake):
        out = dna.run(db, w.t.id)
    assert out["status"] == "ready" and out["prompt_version"] == "marketing-brand-dna-v2"
    assert "attached bathroom" in seen["user"] and "Bed linen" in seen["user"] and "Slow trips" in seen["user"]
    assert "knowledge base" in seen["system"] and out["sources"]["knowledge"] == 2 and out["sources"]["ads"] == 2


def test_grounded_price_mode_adds_payment_terms_like_the_concierge(db):
    w = _business(db)
    w.t.brand_config = {"price_disclosure": "grounded"}
    db.commit()
    assert dna.sources(db, w.t)["business_data"]["payment_policy"]["advance_percent"] is not None


def test_every_studio_step_gets_the_shared_facts_and_grounding_accepts_their_numbers(db):
    w = _business(db)
    facts = ai._facts(db, w.t)
    assert "knowledge" in facts and facts["business_data"]["packages"][0]["included_km"] in (600, "600")
    item = svc.create_item(db, w.t.id, kind="post", title="Coorg weekend", actor_id=w.owner.id)
    db.commit()
    seen = {}

    def fake(task, tenant_id, system, user, tool):
        seen["user"] = user
        return {"caption": "600 km of coffee country, included.", "hashtags": ["coorg"]}, {"model": "m"}, "nvidia"
    with patch.object(ai, "_call", side_effect=fake):
        ai.run_content(db, w.t.id, item.id, w.owner.id, None)
    assert "Bed linen" in seen["user"] and "attached bathroom" in seen["user"]
    assert marketing_lint.grounding("caption", "600 km included", str(facts), strict=True) == []
    assert marketing_lint.grounding("caption", "750 km included", str(facts), strict=True)[0]["rule"] == "unverified_number"
