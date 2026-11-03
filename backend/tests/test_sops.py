"""Dynamic SOPs, phase S1 (migration 188, docs/sops/DYNAMIC_SOPS_PLAN.md): platform rules catalogue, version generation
(code fills + AI text behind the price/lint guards), progress kept across versions, evidence, automatic checks, the API
(happy path, wrong role, assigned staff, cross-tenant) and tenant isolation."""

import pytest

from app.models.audit_event import AuditEvent
from app.models.integration import Integration
from app.models.media_asset import MediaAsset
from app.models.sop import SopInstance, SopStepProgress, SopVersion
from app.models.user import UserRole
from app.schemas.sops import StartIn
from app.services import marketing_ai_service as ai
from app.services.sops import catalogue, checks, generate, rules
from app.services.sops import service as svc
from tests.conftest import seed_capabilities
from tests.ops_helpers import prop, tenant
from tests.test_increment1_defect_specs import _h, _user


@pytest.fixture()
def w(db):
    t = tenant(db)
    t.business_type, t.brand_name = "caravan", "Wanderwheels"
    t.brand_config = {
        "business_profile": {
            "description": "Two caravans for road trips from Bengaluru.",
            "tagline": "Caravan road trips from Bengaluru",
        }
    }
    p = prop(db, t.id, "Van 1")
    owner = _user(db, t.id, UserRole.OWNER)
    db.commit()
    return type("W", (), {"t": t, "p": p, "owner": owner})()


def _started(db, w, key="gbp_setup"):
    inst = svc.start(db, w.t, StartIn(template_key=key), w.owner.id)
    generate.make_version(db, w.t, inst, reason="first", actor_id=w.owner.id, use_ai=False)
    db.commit()
    return inst


def _step(db, w, inst, key):
    return next(s for s in svc.view(db, w.t, inst)["steps"] if s["key"] == key)


# ── Catalogue + rules ───────────────────────────────────────────────────────────────────────────────────────────────


def test_rules_load_and_every_template_reference_exists():
    assert len(rules.digest()) == 64
    for t in catalogue.TEMPLATES:
        assert t.recurrence in ("one_off", "weekly", "monthly", "seasonal")
        assert len({s.key for s in t.steps}) == len(t.steps)
        for s in t.steps:
            assert s.verify in catalogue.VERIFY
            assert all(rules.get(k) for k in s.rules), (t.key, s.key)
            assert s.verify != "auto" or s.check in checks.CHECKS, (t.key, s.key)
            assert all(
                slot
                in {
                    "categories",
                    "photos",
                    "nap",
                    "website",
                    "links_url",
                    "whatsapp_number",
                    "amenities",
                    "ig_name",
                    "highlights",
                    "logo",
                    *generate.AI_SLOTS,
                }
                for slot in s.slots
            )


def test_categories_come_only_from_the_catalogue_and_say_when_not_confirmed():
    cats = rules.categories("google_business", "caravan")
    assert cats[0]["name"] == "Recreational vehicle rental agency" and cats[0]["status"] == "unverified"
    assert cats[0]["as_of"] == "2026-11-03" and "team" in cats[0]["source_note"].lower()
    assert rules.categories("google_business", "boutique_hotel") == []  # nothing curated: check in the platform
    with pytest.raises(ValueError):  # a verified rule needs a source link
        from app.schemas.sops import RuleEntry

        RuleEntry.model_validate(
            {
                "key": "x.y",
                "platform": "instagram",
                "kind": "advice",
                "value": 1,
                "status": "verified",
                "as_of": "2026-11-03",
                "source_note": "abc",
            }
        )


# ── Generation ──────────────────────────────────────────────────────────────────────────────────────────────────────


def test_version_is_filled_from_shared_data_and_never_guesses(db, w):
    inst = _started(db, w)
    cat = _step(db, w, inst, "category")
    assert cat["categories"][0]["name"] == "Recreational vehicle rental agency"
    nap = _step(db, w, inst, "nap")
    assert nap["values"][0] == {"label": "Name", "text": "Wanderwheels"}
    assert {n["href"] for n in nap["needs"]} >= {"/dashboard/properties", "/dashboard/marketing/studio?tab=profile"}
    desc = _step(db, w, inst, "description")
    assert desc["values"][0]["text"] == "Two caravans for road trips from Bengaluru." and not desc["values"][0]["ai"]
    assert _step(db, w, inst, "website")["needs"][0]["href"] == "/dashboard/marketing/website"
    v = db.get(SopVersion, inst.current_version_id)
    assert v.version_no == 1 and v.reason == "first" and v.model is None
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="sop.version_created").count() == 1


def test_versions_are_immutable(db, w):
    inst = _started(db, w)
    v = db.get(SopVersion, inst.current_version_id)
    v.reason = "edited"
    with pytest.raises(ValueError):
        db.flush()
    db.rollback()


def test_photos_follow_the_rule_order_and_skip_people_without_ok(db, w):
    def asset(subjects, people=False, ok=False):
        a = MediaAsset(
            tenant_id=w.t.id,
            storage_key="k",
            mime_type="image/jpeg",
            bytes=1,
            sha256="0" * 64,
            status="active",
            people_ok=ok,
            tags={"subjects": subjects, "people": people, "quality": 4, "description": "x"},
        )
        db.add(a)
        db.flush()
        return a.id

    bath, outside, crowd = asset(["bathroom"]), asset(["exterior"]), asset(["people"], people=True)
    inst = _started(db, w)
    ids = [p["asset_id"] for p in _step(db, w, inst, "photos")["photos"]]
    assert ids == [outside, bath] and crowd not in ids


def test_ai_text_is_guarded_by_price_policy_and_grounding(db, w, monkeypatch):
    monkeypatch.setattr(
        ai,
        "_call",
        lambda *a, **k: (
            {
                "description": "Our caravans start at ₹15,000 per night.",  # handoff mode: no prices in public text
                "short_bio": "Caravan road trips from Bengaluru. Book on WhatsApp.",
                "qa": [
                    {"q": "How far is the airport?", "a": "It is 12 km away."},  # 12 km is not in the facts: dropped
                    {"q": "Where do trips start?", "a": "From Bengaluru."},
                ],
            },
            {"model": "gpt-oss-20b"},
            "nvidia",
        ),
    )
    inst = svc.start(db, w.t, StartIn(template_key="gbp_setup"), w.owner.id)
    v = generate.make_version(db, w.t, inst, reason="first", actor_id=None)
    db.commit()
    desc = _step(db, w, inst, "description")["values"][0]
    assert "15,000" not in desc["text"] and not desc["ai"]  # fell back to the owner's own words
    qa = _step(db, w, inst, "qa")["values"]
    assert [q["label"] for q in qa] == ["Where do trips start?"]
    assert v.model == "gpt-oss-20b" and v.prompt_version == "sop-generate-v1" and "description" in v.ai_note


def test_new_version_keeps_ticks_on_unchanged_steps(db, w):
    inst = _started(db, w)
    svc.mark(db, inst, "claim", "done", w.owner.id)
    svc.mark(db, inst, "nap", "done", w.owner.id)
    w.p.address, w.p.city = "12 MG Road", "Bengaluru"
    generate.make_version(db, w.t, inst, reason="manual", actor_id=w.owner.id, use_ai=False)
    db.commit()
    claim, nap = _step(db, w, inst, "claim"), _step(db, w, inst, "nap")
    assert claim["status"] == "done" and not claim["changed"]
    assert nap["status"] == "todo" and nap["changed"]  # its address changed: check again
    assert db.get(SopVersion, inst.current_version_id).version_no == 2


def test_evidence_step_needs_a_screenshot_or_link(db, w):
    inst = _started(db, w)
    with pytest.raises(svc.SopError) as e:
        svc.mark(db, inst, "verify", "done", w.owner.id)
    assert e.value.code == "evidence_needed"
    svc.add_evidence_link(db, inst, "verify", "https://example.com/shot.png", w.owner.id)
    svc.mark(db, inst, "verify", "done", w.owner.id)
    assert _step(db, w, inst, "verify")["status"] == "done"


def test_evidence_file_is_a_private_asset_never_in_the_library(db, w, monkeypatch):
    monkeypatch.setattr("app.services.media_storage._put", lambda *a, **k: None)
    inst = _started(db, w)
    svc.add_evidence_file(db, inst, "category", b"\x89PNG....", "image/png", w.owner.id)
    a = db.query(MediaAsset).filter_by(tenant_id=w.t.id, source="sop_evidence").one()
    assert a.status == "evidence" and a.storage_key.startswith(f"{w.t.id}/sops/")


def test_finishing_every_step_closes_the_checklist_and_customising_reopens_it(db, w):
    inst = _started(db, w, "whatsapp_profile")
    for s in svc.view(db, w.t, inst)["steps"]:
        if s["verify"] != "manual":
            svc.add_evidence_link(db, inst, s["key"], "https://example.com/x", w.owner.id)
        svc.mark(db, inst, s["key"], "done", w.owner.id)
    assert inst.status == "done"
    from app.schemas.sops import PatchIn

    svc.patch(db, inst, PatchIn(extra_steps=[{"key": "custom_menu", "title": "Add our menu"}]), w.owner.id)
    assert inst.status == "active" and svc.view(db, w.t, inst)["total"] == 7


# ── Automatic checks ────────────────────────────────────────────────────────────────────────────────────────────────


def test_checks_tick_auto_steps_and_untick_when_they_fail(db, w):
    inst = _started(db, w, "instagram_profile")
    svc.run_checks(db, w.t, inst)
    con = _step(db, w, inst, "connect")
    assert con["status"] == "todo" and con["check_result"]["result"] == "fail"
    assert _step(db, w, inst, "bio")["check_result"]["result"] == "unknown"  # no token: asks for a screenshot
    integ = Integration(tenant_id=w.t.id, kind="instagram", status="active", config={})
    db.add(integ)
    db.flush()
    svc.run_checks(db, w.t, inst)
    con = _step(db, w, inst, "connect")
    assert con["status"] == "done" and con["done_by"] is None
    integ.status = "disconnected"
    db.flush()
    svc.run_checks(db, w.t, inst)
    assert _step(db, w, inst, "connect")["status"] == "todo"


# ── Tenant isolation ────────────────────────────────────────────────────────────────────────────────────────────────


def test_one_tenant_never_sees_another_tenants_checklists(db, w):
    inst = _started(db, w)
    other = tenant(db)
    with pytest.raises(svc.SopError) as e:
        svc.get(db, other.id, inst.id)
    assert e.value.status == 404
    assert svc.list_view(db, other)["instances"] == []
    with pytest.raises(svc.SopError):
        svc.start(db, w.t, StartIn(template_key="gbp_setup"), w.owner.id)  # one live checklist per template


# ── API ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture()
def api(db, w, monkeypatch):
    seed_capabilities(db, w.t.id)
    queued = []
    monkeypatch.setattr("app.workers.tasks.sops.generate_version.delay", lambda *a: queued.append(a))
    monkeypatch.setattr("app.workers.tasks.sops.check_instance.delay", lambda *a: queued.append(a))
    return type(
        "A",
        (),
        {
            "mgr": _user(db, w.t.id, UserRole.MANAGER),
            "foh": _user(db, w.t.id, UserRole.FOH),
            "mkt": _user(db, w.t.id, UserRole.MARKETING),
            "compliance": _user(db, w.t.id, UserRole.COMPLIANCE),
            "queued": queued,
        },
    )()


def test_api_start_view_tick(client, db, w, api):
    listing = client.get("/api/v1/sops", headers=_h(api.mgr)).json()
    assert {a["template_key"] for a in listing["available"]} == {"gbp_setup", "instagram_profile", "whatsapp_profile"}
    r = client.post("/api/v1/sops", json={"template_key": "gbp_setup"}, headers=_h(api.mgr))
    assert r.status_code == 201
    sid = r.json()["id"]
    assert api.queued[0][1] == sid
    generate.make_version(db, w.t, db.get(SopInstance, sid), reason="first", actor_id=None, use_ai=False)
    db.commit()
    detail = client.get(f"/api/v1/sops/{sid}", headers=_h(api.mkt)).json()
    assert detail["total"] == 13 and detail["can_work"]
    r = client.post(f"/api/v1/sops/{sid}/steps/claim/done", headers=_h(api.mkt))
    assert r.status_code == 200 and r.json()["done"] == 1
    assert (
        client.post(f"/api/v1/sops/{sid}/steps/verify/done", headers=_h(api.mkt)).json()["detail"]["code"]
        == "evidence_needed"
    )
    assert client.post(f"/api/v1/sops/{sid}/regenerate", headers=_h(api.mgr)).status_code == 202
    assert client.get(f"/api/v1/sops/{sid}/versions", headers=_h(api.mgr)).json()[0]["no"] == 1
    assert client.post(f"/api/v1/sops/{sid}/check", headers=_h(api.mkt)).status_code == 202


def test_api_roles(client, db, w, api):
    assert client.post("/api/v1/sops", json={"template_key": "gbp_setup"}, headers=_h(api.foh)).status_code == 403
    assert client.post("/api/v1/sops", json={"template_key": "gbp_setup"}, headers=_h(api.mkt)).status_code == 403
    assert client.get("/api/v1/sops", headers=_h(api.compliance)).status_code == 403
    inst = _started(db, w)
    assert client.post(f"/api/v1/sops/{inst.id}/steps/claim/done", headers=_h(api.foh)).status_code == 403
    r = client.patch(f"/api/v1/sops/{inst.id}", json={"assignee_id": api.foh.id}, headers=_h(api.mgr))
    assert r.status_code == 200
    assert client.post(f"/api/v1/sops/{inst.id}/steps/claim/done", headers=_h(api.foh)).status_code == 200
    assert client.patch(f"/api/v1/sops/{inst.id}", json={"status": "paused"}, headers=_h(api.foh)).status_code == 403


def test_api_cross_tenant(client, db, w, api):
    inst = _started(db, w)
    other = tenant(db)
    seed_capabilities(db, other.id)
    om = _user(db, other.id, UserRole.MANAGER)
    assert client.get(f"/api/v1/sops/{inst.id}", headers=_h(om)).status_code == 404
    assert client.post(f"/api/v1/sops/{inst.id}/steps/claim/done", headers=_h(om)).status_code == 404
    assert client.patch(f"/api/v1/sops/{inst.id}", json={"status": "archived"}, headers=_h(om)).status_code == 404
    assert client.patch(f"/api/v1/sops/{inst.id}", json={"assignee_id": om.id}, headers=_h(api.mgr)).status_code == 422
    assert db.query(SopStepProgress).filter_by(instance_id=inst.id, status="done").count() == 0
