"""'Change something' (website_change.py): the owner types a change; the scripted model answers with edits that HAIP applies,
validates and saves as the draft. Covers the small-model first try, the retry after a bad edit, a polite "can't do that",
Undo, roles and another workspace's job."""
from app.models.website import SiteAiJob, SiteVersion
from app.services import website_builder_ai as ai
from tests.test_website_art_director import script  # noqa: F401
from tests.website_fixtures import make_tenant, wsite  # noqa: F401

B = "/api/v1/websites/builder"


def _made(client, wsite):  # noqa: F811
    r = client.post("/api/v1/websites/make", headers=wsite["owner_h"])
    assert r.status_code == 201, r.text
    return r.json()["doc"]


def _change(client, db, wsite, script, text, answers):  # noqa: F811
    script["queue"].extend(answers)
    r = client.post(f"{B}/change", json={"text": text}, headers=wsite["owner_h"])
    assert r.status_code == 202, r.text
    job = ai.run(db, wsite["tenant"].id, r.json()["id"])
    db.commit()
    return job


def test_a_change_runs_on_the_small_model_and_saves_the_draft(client, db, wsite, script):  # noqa: F811
    _made(client, wsite)
    job = _change(client, db, wsite, script, "Make the top say we're in Coorg and change my WhatsApp to 98450 11111", [{
        "reply": "Done: the top now mentions Coorg and WhatsApp buttons use your new number.",
        "ops": [{"op": "set_text", "section_id": "hero", "field": "headline", "value": "Quiet villas in *Coorg*"},
                {"op": "set_contact", "field": "whatsapp", "value": "+91 98450 11111"}]}])
    assert job.status == "ready" and job.result["attempts"] == 1 and script["calls"][-1][0] == "website_change"
    doc = db.get(SiteVersion, job.result_version_id).doc
    assert doc["pages"][0]["sections"][0]["slots"]["headline"] == "Quiet villas in *Coorg*"
    assert doc["site"]["contact"]["whatsapp"] == "+91 98450 11111"
    assert job.result["artifact"]["can_undo"] is True and "before" not in client.get(f"{B}/jobs/{job.id}", headers=wsite["owner_h"]).json()


def test_a_bad_edit_is_retried_on_the_stronger_model_then_applied(client, db, wsite, script):  # noqa: F811
    _made(client, wsite)
    job = _change(client, db, wsite, script, "Add our reviews", [
        {"reply": "Added.", "ops": [{"op": "add_section", "section_type": "testimonials"}]},          # no such type
        {"reply": "Added a reviews section above the contact details.", "ops": [{"op": "add_section", "section_type": "reviews",
                                                                                "variant": "grid"}]}])
    assert job.status == "ready" and job.result["attempts"] == 2 and script["calls"][-1][0] == "website_plan"
    types = [s["type"] for s in db.get(SiteVersion, job.result_version_id).doc["pages"][0]["sections"]]
    assert types.index("reviews") < types.index("contact")


def test_a_typed_price_never_reaches_the_site(client, db, wsite, script):  # noqa: F811
    _made(client, wsite)
    job = _change(client, db, wsite, script, "say villas from 12000", [
        {"reply": "Done.", "ops": [{"op": "set_text", "section_id": "hero", "field": "subhead", "value": "Villas from ₹12,000 a night"}]},
        {"reply": "Done.", "ops": [{"op": "set_text", "section_id": "hero", "field": "subhead", "value": "Rs 12000 only"}]}])
    assert job.status == "failed" and job.result_version_id is None
    assert "12,000" not in str(client.get("/api/v1/websites/draft", headers=wsite["owner_h"]).json()["doc"])


def test_a_request_it_cannot_do_changes_nothing(client, db, wsite, script):  # noqa: F811
    doc = _made(client, wsite)
    job = _change(client, db, wsite, script, "take card payments", [
        {"reply": "Taking payment on the website isn't available yet; guests can send a booking request instead.", "ops": []}])
    assert job.status == "ready" and job.result_version_id is None and job.result["artifact"]["can_undo"] is False
    assert client.get("/api/v1/websites/draft", headers=wsite["owner_h"]).json()["doc"] == doc


def test_undo_puts_the_page_back(client, db, wsite, script):  # noqa: F811
    before = _made(client, wsite)
    job = _change(client, db, wsite, script, "remove the stays", [
        {"reply": "Removed the stays section.", "ops": [{"op": "remove_section", "section_id": "stays"}]}])
    assert client.post(f"{B}/change/{job.id}/undo", headers=wsite["owner_h"]).status_code == 200
    db.expire_all()
    assert client.get("/api/v1/websites/draft", headers=wsite["owner_h"]).json()["doc"] == before
    assert client.post(f"{B}/change/{job.id}/undo", headers=wsite["owner_h"]).status_code == 404     # only once


def test_change_needs_website_approve_and_stays_in_its_workspace(client, db, wsite, script):  # noqa: F811
    _made(client, wsite)
    assert client.post(f"{B}/change", json={"text": "make it blue"}, headers=wsite["foh_h"]).status_code == 403
    assert client.post(f"{B}/change", json={"text": "make it blue"}, headers=wsite["mkt_h"]).status_code == 403
    from app.services.website_service import create_site
    other = make_tenant(db, "Elsewhere")
    other_site = create_site(db, other, actor_id=None)          # a real site: PostgreSQL enforces site_ai_jobs.site_id
    stranger = SiteAiJob(tenant_id=other.id, site_id=other_site.id, kind="change", status="ready", request="x", result={"before": {"a": 1}})
    db.add(stranger)
    db.commit()
    assert client.post(f"{B}/change/{stranger.id}/undo", headers=wsite["owner_h"]).status_code == 404


def test_owner_text_can_be_added_written_and_given_a_photo():
    import uuid
    from app.schemas.site_builder import ChangeOp
    from app.services import website_change as wc
    from tests.test_website_spec_v2 import spec
    from app.services import website_spec_service as wspec
    photo = str(uuid.uuid4())
    doc = wspec.validate(spec())
    out = wc.apply_ops(doc, [ChangeOp(op="add_section", section_type="text", variant="with-photo"),
                             ChangeOp(op="set_text", section_id="text", field="heading", value="House rules"),
                             ChangeOp(op="set_text", section_id="text", field="body", value="Pets welcome. " * 60),
                             ChangeOp(op="set_photo", section_id="text", value=photo)], {photo})
    sec = next(s for s in out["pages"][0]["sections"] if s["type"] == "text")
    assert out["pages"][0]["sections"][-1]["type"] == "contact"           # added before contact, never after it
    assert sec["slots"]["heading"] == "House rules" and sec["slots"]["media"] == f"asset:{photo}" and len(sec["slots"]["body"]) > 300
