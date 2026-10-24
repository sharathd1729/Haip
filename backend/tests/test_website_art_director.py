"""Website art director (W2): brief -> sitemap -> wireframe -> style directions -> v2 draft. The model is scripted (the real
tool call is replaced), so the checks, the one validation retry, approvals, staleness and the assembled draft are real."""
import copy

import pytest

from app.models.website import SiteAiJob, SiteVersion
from app.services import website_builder_ai as ai
from app.services import website_builder_service as wbs
from tests.test_website_spec_v2 import PRICE_RE, _data, _photo
from tests.website_fixtures import make_tenant, wsite  # noqa: F401

B = "/api/v1/websites/builder"

SITEMAP = {"note": "Lead with the road, then the journeys.", "pages": [
    {"slug": "/", "title": "Home", "nav": False, "reason": "Where every enquiry starts", "sections": [
        {"type": "hero", "reason": "Show the caravan at dawn"}, {"type": "packages", "reason": "What guests can book"},
        {"type": "faq", "reason": "Answer the usual doubts"}, {"type": "contact", "reason": "One tap to WhatsApp"}]},
    {"slug": "/journeys", "title": "Journeys", "nav": True, "reason": "The routes in detail", "sections": [
        {"type": "itinerary", "reason": "Day by day"}, {"type": "booking-cta", "reason": "Close with a clear ask"}]}]}

WIREFRAME = {"note": "", "pages": [
    {"slug": "/", "title": "Home", "nav": False, "seo_title": "Coorg caravan trips",
     "seo_description": "Two-night caravan journeys into the coffee hills with a driver-host and breakfast on the road.",
     "sections": [
         {"id": "hero", "type": "hero", "variant": "fullbleed-image", "headline": "Wake up where the *road* ends",
          "subhead": "Your own room on wheels.", "cta_label": "Plan my trip"},
         {"id": "packages", "type": "packages", "variant": "cards-3", "heading": "Pick the pace"},
         {"id": "faq", "type": "faq", "variant": "accordion", "heading": "Good to know"},
         {"id": "contact", "type": "contact", "variant": "split", "heading": "Find us"}]},
    {"slug": "/journeys", "title": "Journeys", "nav": True, "sections": [
        {"id": "route", "type": "itinerary", "variant": "timeline", "heading": "Coorg in two nights"},
        {"id": "cta", "type": "booking-cta", "variant": "banner", "heading": "Tell us your dates"}]}]}

STYLE = {"note": "", "directions": [
    {"name": "Estate Morning", "mood": "Warm paper and olive for coffee country.", "palette_preset": "estate-olive",
     "display": "fraunces", "body": "figtree", "radius": "soft", "sample_headline": "Three mornings, zero check-ins"},
    {"name": "Monsoon Road", "mood": "Slate and rust for the rains.", "palette_preset": "monsoon-slate",
     "display": "bricolage", "body": "inter", "radius": "sharp", "sample_headline": "Wake up where the road ends"},
    {"name": "Brand Green", "mood": "Built from the brand kit.", "ink": "#1B2420", "surface": "#F7F4EC", "primary": "#2F5D46",
     "accent": "#A8641C", "display": "instrument-serif", "body": "manrope", "radius": "pill", "sample_headline": "Your room on the road"}]}


@pytest.fixture()
def script(monkeypatch):
    """Replace the router call with queued answers; records every (task, user message)."""
    queue, calls = [], []

    def fake(task, tenant_id, system, user, tool):
        calls.append((task, user, tool["name"]))
        return copy.deepcopy(queue.pop(0)), {"model": f"test-{task}", "input_tokens": 10, "output_tokens": 20}, "gemini"
    monkeypatch.setattr("app.services.marketing_ai_service._call", fake)
    queued = []
    monkeypatch.setattr("app.workers.tasks.website.builder_step",
                        type("T", (), {"delay": staticmethod(lambda *a: queued.append(a))}))
    return {"queue": queue, "calls": calls, "queued": queued}


def _run(client, db, wsite, step, answers, script, feedback=None):
    script["queue"].extend(answers)
    r = client.post(f"{B}/steps/{step}/run", json={"feedback": feedback}, headers=wsite["owner_h"])
    assert r.status_code == 202, r.text
    job_id = script["queued"][-1][1]
    ai.run(db, wsite["tenant"].id, job_id)
    db.commit()
    return db.get(SiteAiJob, job_id)


def _approve(client, wsite, step, job_id):
    r = client.post(f"{B}/steps/{step}/approve", json={"job_id": job_id}, headers=wsite["owner_h"])
    assert r.status_code == 200, r.text
    return r.json()


def test_full_flow_brief_to_v2_draft(client, db, wsite, script):
    _data(db, wsite["tenant"].id)
    _photo(db, wsite["tenant"].id)
    r = client.post(f"{B}/brief", json={"owner": {"goals": ["More weekend enquiries on WhatsApp"], "avoid": ["cheap"]}},
                    headers=wsite["owner_h"])
    assert r.status_code == 200, r.text
    st = r.json()
    facts = st["brief"]["facts"]
    assert st["next"] == "sitemap" and facts["packages"][0]["key"] == "coorg-signature" and facts["content"]["faq_count"] == 1
    assert facts["price_policy"] == "handoff" and facts["content"]["reviews_usable"] == 1

    sm = _run(client, db, wsite, "sitemap", [SITEMAP], script)
    assert sm.status == "ready" and sm.result["artifact"]["pages"][0]["sections"][0]["reason"] == "Show the caravan at dawn"
    assert script["calls"][-1][0] == "website_plan" and "coorg-signature" in script["calls"][-1][1]
    # wireframe can't run before the sitemap is approved
    assert client.post(f"{B}/steps/wireframe/run", json={}, headers=wsite["owner_h"]).status_code == 409
    _approve(client, wsite, "sitemap", sm.id)

    wf = _run(client, db, wsite, "wireframe", [WIREFRAME], script)
    assert wf.status == "ready", wf.error
    _approve(client, wsite, "wireframe", wf.id)

    style = _run(client, db, wsite, "style", [STYLE], script)
    assert style.status == "ready", style.error
    dirs = style.result["artifact"]["directions"]
    assert [d["tokens"]["palette"]["name"] for d in dirs] == ["estate-olive", "monsoon-slate", "brand-green"]
    assert client.post(f"{B}/steps/style/approve", json={"job_id": style.id}, headers=wsite["owner_h"]).status_code == 422

    r = client.post(f"{B}/style/pick", json={"job_id": style.id, "index": 2}, headers=wsite["owner_h"])
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["next"] == "done" and out["draft_version_id"] == out["version"]["id"]
    v = db.get(SiteVersion, out["version"]["id"])
    assert v.doc["spec_version"] == 2 and v.origin == "ai" and v.doc["tokens"]["display"] == "instrument-serif"
    assert v.doc["pages"][0]["sections"][0]["slots"]["headline"] == "Wake up where the *road* ends"
    assert v.doc["site"]["contact"]["phone"] == "+919876543210"
    boot = client.get("/api/v1/websites/live-data", headers=wsite["owner_h"]).json()
    assert boot["spec_version"] == 2 and boot["bound"]["packages"]["items"][0]["key"] == "coorg-signature"
    assert not PRICE_RE.search(str(boot["bound"]))


def test_invalid_answer_is_retried_once_with_the_problems(client, db, wsite, script):
    _data(db, wsite["tenant"].id)
    client.post(f"{B}/brief", json={}, headers=wsite["owner_h"])
    bad = copy.deepcopy(SITEMAP)
    bad["pages"][0]["sections"][0]["type"] = "carousel"
    sm = _run(client, db, wsite, "sitemap", [bad, SITEMAP], script)
    assert sm.status == "ready" and sm.result["attempts"] == 2
    assert "FAILED HAIP'S CHECKS" in script["calls"][-1][1] and "type" in script["calls"][-1][1]


def test_invalid_twice_fails_with_a_clear_error(client, db, wsite, script):
    _data(db, wsite["tenant"].id)
    client.post(f"{B}/brief", json={}, headers=wsite["owner_h"])
    sm = _run(client, db, wsite, "sitemap", [SITEMAP], script)
    _approve(client, wsite, "sitemap", sm.id)
    priced = copy.deepcopy(WIREFRAME)
    priced["pages"][0]["sections"][0]["subhead"] = "Only Rs 18,000 a night"
    reordered = copy.deepcopy(WIREFRAME)
    reordered["pages"][0]["sections"].reverse()
    wf = _run(client, db, wsite, "wireframe", [priced, reordered], script)
    assert wf.status == "failed" and "checks twice" in wf.error and "approved sitemap" in wf.error


def test_bad_contrast_direction_is_rejected(client, db, wsite, script):
    _data(db, wsite["tenant"].id)
    client.post(f"{B}/brief", json={}, headers=wsite["owner_h"])
    _approve(client, wsite, "sitemap", _run(client, db, wsite, "sitemap", [SITEMAP], script).id)
    _approve(client, wsite, "wireframe", _run(client, db, wsite, "wireframe", [WIREFRAME], script).id)
    grey = copy.deepcopy(STYLE)
    grey["directions"][2].update(ink="#888888", surface="#999999")
    style = _run(client, db, wsite, "style", [grey, grey], script)
    assert style.status == "failed" and "contrast" in style.error


def test_feedback_reruns_and_reapproving_makes_later_steps_stale(client, db, wsite, script):
    _data(db, wsite["tenant"].id)
    client.post(f"{B}/brief", json={}, headers=wsite["owner_h"])
    sm = _run(client, db, wsite, "sitemap", [SITEMAP], script)
    _approve(client, wsite, "sitemap", sm.id)
    _approve(client, wsite, "wireframe", _run(client, db, wsite, "wireframe", [WIREFRAME], script).id)
    again = _run(client, db, wsite, "sitemap", [SITEMAP], script, feedback="Add an about page")
    assert "THE OWNER ASKED FOR THESE CHANGES: Add an about page" in script["calls"][-1][1]
    assert again.request == "Add an about page"
    st = _approve(client, wsite, "sitemap", again.id)
    assert st["steps"]["wireframe"]["approved_id"] is None and st["next"] == "wireframe"
    # the old sitemap can no longer be approved
    r = client.post(f"{B}/steps/sitemap/approve", json={"job_id": sm.id}, headers=wsite["owner_h"])
    assert r.status_code == 409


def test_copy_polish_runs_on_the_small_model_and_saves_the_draft(client, db, wsite, script):
    from tests.test_website_spec_v2 import spec
    client.post("/api/v1/websites/draft/v2", json={"spec": spec()}, headers=wsite["owner_h"])
    script["queue"].extend([{"text": "Only Rs 999!"}, {"text": "Wake up where the *river* bends"}])
    r = client.post(f"{B}/copy", json={"slug": "/", "section_id": "hero", "slot": "headline", "instruction": "make it about the river"},
                    headers=wsite["owner_h"])
    assert r.status_code == 202, r.text
    job = ai.run(db, wsite["tenant"].id, r.json()["id"])
    db.commit()
    assert job.status == "ready" and job.result["attempts"] == 2 and script["calls"][-1][0] == "website_copy"
    head = db.get(SiteVersion, job.result_version_id)
    assert head.doc["pages"][0]["sections"][0]["slots"]["headline"] == "Wake up where the *river* bends"
    bad = client.post(f"{B}/copy", json={"slug": "/", "section_id": "hero", "slot": "heading", "instruction": "x" * 5},
                      headers=wsite["owner_h"])
    assert bad.status_code == 422                                         # hero has no "heading" slot


@pytest.mark.parametrize("who", ["mkt_h", "foh_h"])
def test_only_owner_or_manager_can_drive_the_art_director(client, wsite, who):
    assert client.get(B, headers=wsite[who]).status_code == 403
    assert client.post(f"{B}/brief", json={}, headers=wsite[who]).status_code == 403
    assert client.post(f"{B}/steps/sitemap/run", json={}, headers=wsite[who]).status_code == 403


def test_manager_can_run_the_flow(client, wsite, script):
    assert client.post(f"{B}/brief", json={}, headers=wsite["manager_h"]).status_code == 200
    assert client.get(B, headers=wsite["manager_h"]).json()["next"] == "sitemap"


def test_jobs_and_state_stay_inside_the_workspace(client, db, wsite, script):
    from app.models.user import UserRole
    from tests.test_marketing_studio_content import make_user
    _data(db, wsite["tenant"].id)
    client.post(f"{B}/brief", json={}, headers=wsite["owner_h"])
    mine = _run(client, db, wsite, "sitemap", [SITEMAP], script)
    other = make_tenant(db, "Elsewhere")
    _, oh = make_user(db, other.id, UserRole.OWNER)
    assert client.get(B, headers=oh).status_code == 404                            # no site there
    assert client.post("/api/v1/websites/site", json={}, headers=oh).status_code == 201
    st = client.get(B, headers=oh).json()
    assert st["brief"] is None and st["steps"]["sitemap"]["latest"] is None
    assert client.get(f"{B}/jobs/{mine.id}", headers=oh).status_code == 404
    r = client.post(f"{B}/steps/sitemap/approve", json={"job_id": mine.id}, headers=oh)
    assert r.status_code == 409 and db.get(SiteAiJob, mine.id).status == "ready"


def test_service_brief_and_chain_are_per_workspace(client, db, wsite):
    from app.models.tenant import Tenant
    from app.models.user import UserRole
    from app.models.website import Site
    from app.services.website_service import WebsiteError
    from tests.test_marketing_studio_content import make_user
    mine = db.query(Site).filter_by(id=wsite["site"]["id"]).one()
    wbs.save_brief(db, wsite["tenant"], mine, wbs.BriefOwner(goals=["More enquiries"]), wsite["owner"])
    db.commit()
    other = make_tenant(db, "Chain")
    owner_b, oh = make_user(db, other.id, UserRole.OWNER)
    assert client.post("/api/v1/websites/site", json={}, headers=oh).status_code == 201
    theirs = db.query(Site).filter_by(tenant_id=other.id).one()
    assert wbs.chain(db, mine)["brief"] is not None and wbs.chain(db, theirs)["brief"] is None
    with pytest.raises(WebsiteError) as e:
        wbs.request_step(db, theirs, "sitemap", owner_b, None)
    assert e.value.code == "previous_step_not_approved"
    assert wbs.brief_facts(db, db.get(Tenant, other.id), theirs)["packages"] == []
