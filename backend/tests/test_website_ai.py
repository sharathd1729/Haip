"""Website builder AI developer: every operation is validated; prices, reviews and system sections are refused;
jobs run through Celery only and save a draft, never publish."""
import json
from pathlib import Path

from app.models.website import SiteAiJob, SiteVersion
from app.services import website_ai_service as ai
from app.services import website_blocks as wb
from app.services.website_ai_prompts import Changes
from tests.website_fixtures import BASE, draft, wsite  # noqa: F401


def _home(doc):
    return doc["pages"][0]


def test_spec_is_identical_in_backend_and_frontend():
    root = Path(__file__).resolve().parents[2]
    front = root / "frontend" / "src" / "site-blocks" / "blocks.json"
    assert json.loads(front.read_text(encoding="utf-8")) == wb.spec(), "copy website_blocks.json to the frontend"


def test_validate_doc_is_idempotent_and_restores_required_pages():
    clean, problems = wb.validate_doc({"pages": [{"key": "home", "content": [{"type": "Hero", "props": {"title": "Hi"}}]}]})
    again, _ = wb.validate_doc(clean)
    assert again == clean
    assert {p["key"] for p in clean["pages"]} >= {"home", "contact", "policies"}
    assert any("required" in p for p in problems)


def test_apply_ops_sets_text_and_refuses_prices_reviews_and_system_sections(db, client, wsite):
    doc = draft(client, wsite["owner_h"])["doc"]
    hero = _home(doc)["content"][0]["props"]["id"]
    ops = [
        {"op": "set", "page_id": "home", "block_id": hero, "field": "title", "value": "Two pool villas in *Coorg*"},
        {"op": "set", "page_id": "home", "block_id": hero, "field": "text", "value": "Stay from ₹4,999 a night"},
        {"op": "add_block", "page_id": "home", "block_type": "Reviews", "block_id": "new1"},
        {"op": "set", "page_id": "home", "block_id": "new1", "field": "items", "value": "Lovely | Asha"},
        {"op": "set", "page_id": "home", "block_id": "new1", "field": "heading", "value": "What guests say"},
        {"op": "add_block", "page_id": "home", "block_type": "BookingEngine"},
        {"op": "remove_block", "page_id": "policies", "block_id": doc["pages"][[p["key"] for p in doc["pages"]].index("policies")]["content"][0]["props"]["id"]},
        {"op": "add_page", "page_id": "newp", "title": "Long stays", "path": "/long-stays"},
        {"op": "add_block", "page_id": "newp", "block_type": "Text", "block_id": "t1"},
        {"op": "set", "page_id": "newp", "block_id": "t1", "field": "heading", "value": "Stay a month"},
        {"op": "set_theme", "pack": "kerala", "personality": "heritage"},
    ]
    new, changes, refused, touched = ai.apply_ops(doc, ops)
    hero_props = _home(new)["content"][0]["props"]
    assert hero_props["title"] == "Two pool villas in *Coorg*" and "₹" not in hero_props["text"]
    reviews = next(b for b in _home(new)["content"] if b["type"] == "Reviews")
    assert reviews["props"]["items"] == [] and reviews["props"]["heading"] == "What guests say"
    assert not any(b["type"] == "BookingEngine" for b in _home(new)["content"])
    assert any(p["key"] == "policies" and p["content"] for p in new["pages"])
    long_page = next(p for p in new["pages"] if p["path"] == "/long-stays")
    assert long_page["content"][0]["props"]["heading"] == "Stay a month"
    assert new["theme"] == {"pack": "kerala", "personality": "heritage"}
    assert any("Prices" in r for r in refused) and any("Reviews" in r for r in refused)
    assert hero in touched


def test_run_job_saves_an_ai_draft_and_never_publishes(db, client, wsite, monkeypatch):
    doc = draft(client, wsite["owner_h"])["doc"]
    hero = _home(doc)["content"][0]["props"]["id"]
    fake = Changes(reply="Made the headline warmer.", ops=[{"op": "set", "page_id": "home", "block_id": hero, "field": "kicker",
                                                          "value": "Pool villas near Madikeri"}])
    monkeypatch.setattr(ai, "_llm", lambda tenant, system, user: (fake, {"model": "test-model", "usage": {}}, "nvidia"))
    calls = []
    monkeypatch.setattr("app.workers.tasks.website.ai_job", type("T", (), {"delay": staticmethod(lambda *a: calls.append(a))}))
    r = client.post(f"{BASE}/ai/edit", json={"message": "Make the hero warmer"}, headers=wsite["mkt_h"])
    assert r.status_code == 202 and len(calls) == 1
    busy = client.post(f"{BASE}/ai/edit", json={"message": "again"}, headers=wsite["mkt_h"])
    assert busy.status_code == 409
    job = ai.run_job(db, wsite["tenant"].id, r.json()["id"])
    db.commit()
    assert job.status == "ready" and job.result["changes"] and job.result["reply"] == "Made the headline warmer."
    v = db.get(SiteVersion, job.result_version_id)
    assert v.status == "draft" and _home(v.doc)["content"][0]["props"]["kicker"] == "Pool villas near Madikeri"
    assert client.get(f"{BASE}/site", headers=wsite["owner_h"]).json()["live"] is None
    got = client.get(f"{BASE}/ai/jobs/{job.id}", headers=wsite["mkt_h"]).json()
    assert got["status"] == "ready"


def test_ai_jobs_need_edit_capability_and_are_tenant_scoped(db, client, wsite):
    from app.models.user import UserRole
    from tests.test_marketing_studio_content import make_user
    from tests.website_fixtures import make_tenant
    assert client.post(f"{BASE}/ai/edit", json={"message": "hello there"}, headers=wsite["foh_h"]).status_code == 403
    other = make_tenant(db, "Rival")
    _, other_h = make_user(db, other.id, UserRole.OWNER)
    job = SiteAiJob(tenant_id=wsite["tenant"].id, site_id=wsite["site"]["id"], kind="edit", request="x", status="ready")
    db.add(job)
    db.commit()
    assert client.get(f"{BASE}/ai/jobs/{job.id}", headers=other_h).status_code == 404
