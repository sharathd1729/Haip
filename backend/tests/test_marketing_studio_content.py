"""Marketing Studio content lifecycle over the REST API: versions, review, approval integrity, roles, tenant isolation."""
import uuid

import pytest

from app.core.security import create_access_token
from app.models.marketing import MarketingApproval, MarketingContentVersion
from app.models.module import Module, WorkspaceModule
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import marketing_content_service as svc
from tests.conftest import seed_capabilities

BASE = "/api/v1/marketing/studio"
POST = {"caption": "Sunrise over the Western Ghats from your own terrace.", "hashtags": ["#luxurystay", "karnataka"],
        "media": {"asset_id": "photo-1"}}     # a draft without a photo cannot be sent for approval (needs_photos)


def seed_photos(db, tenant_id, n=2):
    """Approved library photos, so the agency's photo step can fill every slot."""
    from app.models.media_asset import MediaAsset
    out = [MediaAsset(id=str(uuid.uuid4()), tenant_id=tenant_id, storage_key=f"{tenant_id}/marketing/{i}.jpg",
                      mime_type="image/jpeg", bytes=10, sha256=uuid.uuid4().hex * 2, status="active", alt_text="the deck")
           for i in range(n)]
    db.add_all(out)
    db.commit()
    return out


def enable_module(db, tenant_id, code="marketing_studio"):
    mod = db.query(Module).filter_by(code=code).first()
    if mod is None:
        mod = Module(id=str(uuid.uuid4()), code=code, name=code)
        db.add(mod)
        db.flush()
    db.add(WorkspaceModule(id=str(uuid.uuid4()), workspace_id=tenant_id, module_id=mod.id, enabled=True))
    db.commit()


def make_user(db, tenant_id, role):
    u = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name=f"{role} user", email=f"{role}-{uuid.uuid4().hex[:6]}@t.com",
             hashed_password="x", role=role, is_active=True)
    db.add(u)
    db.commit()
    token = create_access_token({"sub": u.id, "tenant_id": tenant_id, "role": role.value})
    return u, {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def ws(db, tenant_and_user):
    tenant = tenant_and_user["tenant"]
    seed_capabilities(db, tenant.id)
    enable_module(db, tenant.id)
    owner_h = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    manager, manager_h = make_user(db, tenant.id, UserRole.MANAGER)
    manager2, manager2_h = make_user(db, tenant.id, UserRole.MANAGER)
    mkt, mkt_h = make_user(db, tenant.id, UserRole.MARKETING)
    return {"tenant": tenant, "owner": tenant_and_user["user"], "owner_h": owner_h, "manager": manager, "manager_h": manager_h,
            "manager2_h": manager2_h, "mkt": mkt, "mkt_h": mkt_h}


@pytest.fixture(autouse=True)
def _library_photo(request):
    """POST names library photo "photo-1": seed it for this module's workspace (other modules import ws, not this)."""
    if "ws" in request.fixturenames:
        db, tenant = request.getfixturevalue("db"), request.getfixturevalue("ws")["tenant"]
        from app.models.media_asset import MediaAsset
        db.add(MediaAsset(id="photo-1", tenant_id=tenant.id, storage_key="k/photo-1.jpg", mime_type="image/jpeg", bytes=10,
                          sha256="a" * 64, status="active"))
        db.commit()


def _create(client, headers, payload=POST, kind="post"):
    r = client.post(f"{BASE}/content", json={"kind": kind, "title": "Monsoon terrace", "payload": payload}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_marketing_writes_owner_approves_and_payload_is_publishable(client, db, ws):
    item = _create(client, ws["mkt_h"])
    vid = item["current"]["id"]
    assert item["status"] == "draft" and item["current"]["version"] == 1 and item["current"]["origin"] == "human"

    assert client.post(f"{BASE}/content/{item['id']}/submit", json={"version_id": vid}, headers=ws["mkt_h"]).json()["status"] == "in_review"
    r = client.post(f"{BASE}/content/{item['id']}/approve", json={"version_id": vid}, headers=ws["owner_h"])
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["approved_version_id"] == vid

    assert svc.approved_payload(db, ws["tenant"].id, item["id"])["caption"] == POST["caption"]
    decisions = [d["decision"] for d in r.json()["decisions"]]
    assert decisions == ["approved", "submitted"]


def test_marketing_role_cannot_approve(client, ws):
    item = _create(client, ws["owner_h"])
    vid = item["current"]["id"]
    client.post(f"{BASE}/content/{item['id']}/submit", json={"version_id": vid}, headers=ws["owner_h"])
    r = client.post(f"{BASE}/content/{item['id']}/approve", json={"version_id": vid}, headers=ws["mkt_h"])
    assert r.status_code == 403


def test_manager_cannot_approve_own_version_but_another_manager_can(client, ws):
    item = _create(client, ws["manager_h"])
    vid = item["current"]["id"]
    client.post(f"{BASE}/content/{item['id']}/submit", json={"version_id": vid}, headers=ws["manager_h"])
    r = client.post(f"{BASE}/content/{item['id']}/approve", json={"version_id": vid}, headers=ws["manager_h"])
    assert r.status_code == 403 and r.json()["detail"]["code"] == "self_approval"
    r = client.post(f"{BASE}/content/{item['id']}/approve", json={"version_id": vid}, headers=ws["manager2_h"])
    assert r.status_code == 200 and r.json()["status"] == "approved"


def test_owner_may_approve_own_version_and_double_click_is_idempotent(client, ws):
    item = _create(client, ws["owner_h"])
    vid = item["current"]["id"]
    client.post(f"{BASE}/content/{item['id']}/submit", json={"version_id": vid}, headers=ws["owner_h"])
    for _ in range(2):
        r = client.post(f"{BASE}/content/{item['id']}/approve", json={"version_id": vid}, headers=ws["owner_h"])
        assert r.status_code == 200 and r.json()["status"] == "approved"
    assert [d["decision"] for d in r.json()["decisions"]].count("approved") == 1


def test_edit_after_approval_voids_it_and_blocks_publishing(client, db, ws):
    item = _create(client, ws["mkt_h"])
    v1 = item["current"]["id"]
    client.post(f"{BASE}/content/{item['id']}/submit", json={"version_id": v1}, headers=ws["mkt_h"])
    client.post(f"{BASE}/content/{item['id']}/approve", json={"version_id": v1}, headers=ws["owner_h"])

    r = client.post(f"{BASE}/content/{item['id']}/versions", json={"payload": {**POST, "caption": "Changed line."}}, headers=ws["mkt_h"])
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "draft" and body["approved_version_id"] is None and body["current"]["version"] == 2
    assert "withdrawn" in [d["decision"] for d in body["decisions"]]
    with pytest.raises(svc.MarketingError) as exc:
        svc.approved_payload(db, ws["tenant"].id, item["id"])
    assert exc.value.code == "not_approved"

    # The reviewer still holding the old version cannot approve it.
    client.post(f"{BASE}/content/{item['id']}/submit", json={"version_id": body["current"]["id"]}, headers=ws["mkt_h"])
    r = client.post(f"{BASE}/content/{item['id']}/approve", json={"version_id": v1}, headers=ws["owner_h"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "version_changed"


def test_tampered_version_cannot_be_approved_or_published(client, db, ws):
    item = _create(client, ws["mkt_h"])
    vid = item["current"]["id"]
    client.post(f"{BASE}/content/{item['id']}/submit", json={"version_id": vid}, headers=ws["mkt_h"])
    v = db.query(MarketingContentVersion).filter_by(id=vid).one()
    v.payload = {**v.payload, "caption": "Edited behind the API's back"}
    db.commit()
    r = client.post(f"{BASE}/content/{item['id']}/approve", json={"version_id": vid}, headers=ws["owner_h"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "integrity_failed"


def test_reject_then_resubmit(client, ws):
    item = _create(client, ws["mkt_h"])
    vid = item["current"]["id"]
    client.post(f"{BASE}/content/{item['id']}/submit", json={"version_id": vid}, headers=ws["mkt_h"])
    r = client.post(f"{BASE}/content/{item['id']}/reject", json={"version_id": vid, "note": "Too long"}, headers=ws["manager_h"])
    assert r.json()["status"] == "rejected"
    r = client.post(f"{BASE}/content/{item['id']}/submit", json={"version_id": vid}, headers=ws["mkt_h"])
    assert r.json()["status"] == "in_review"


def test_price_is_blocked_in_handoff_workspace_and_allowed_when_grounded(client, db, ws):
    r = client.post(f"{BASE}/content", json={"kind": "post", "title": "x", "payload": {"caption": "Stay from Rs 12,000 per night"}},
                    headers=ws["mkt_h"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "content_not_allowed"

    ws["tenant"].brand_config = {"price_disclosure": "grounded"}
    db.commit()
    r = client.post(f"{BASE}/content", json={"kind": "post", "title": "x", "payload": {"caption": "Stay from Rs 12,000 per night"}},
                    headers=ws["mkt_h"])
    assert r.status_code == 201


def test_banned_words_from_profile_are_blocked(client, ws):
    assert client.put(f"{BASE}/profile", json={"avoid": ["cheap"]}, headers=ws["owner_h"]).status_code == 200
    r = client.post(f"{BASE}/content", json={"kind": "post", "title": "x", "payload": {"caption": "A cheap getaway"}}, headers=ws["mkt_h"])
    assert r.status_code == 422 and "cheap" in " ".join(r.json()["detail"]["problems"])


@pytest.mark.parametrize("kind,payload", [
    ("carousel", {"caption": "x", "slides": [{"headline": "only one"}]}),
    ("post", {"caption": "x", "hashtags": [f"#t{i}" for i in range(31)]}),
    ("post", {"caption": "x" * 2201}),
    ("post", {"caption": "x", "script": "<script>alert(1)</script>"}),
])
def test_schema_rejects_bad_payloads(client, ws, kind, payload):
    r = client.post(f"{BASE}/content", json={"kind": kind, "title": "x", "payload": payload}, headers=ws["mkt_h"])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_content"


def test_profile_validation(client, ws):
    r = client.put(f"{BASE}/profile", json={"gstin": "not-a-gstin"}, headers=ws["owner_h"])
    assert r.status_code == 422
    r = client.put(f"{BASE}/profile", json={"tagline": "Caravans, done properly", "default_hashtags": ["roadtrip"]}, headers=ws["owner_h"])
    assert r.status_code == 200 and r.json()["profile"]["default_hashtags"] == ["#roadtrip"]


def test_module_off_is_refused(client, db, ws):
    db.query(WorkspaceModule).filter_by(workspace_id=ws["tenant"].id).delete()
    db.commit()
    r = client.get(f"{BASE}/content", headers=ws["owner_h"])
    assert r.status_code == 403


def test_other_tenant_cannot_see_or_approve(client, db, ws):
    item = _create(client, ws["mkt_h"])
    vid = item["current"]["id"]
    client.post(f"{BASE}/content/{item['id']}/submit", json={"version_id": vid}, headers=ws["mkt_h"])

    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    seed_capabilities(db, other.id)
    enable_module(db, other.id)
    _, other_owner_h = make_user(db, other.id, UserRole.OWNER)

    assert client.get(f"{BASE}/content/{item['id']}", headers=other_owner_h).status_code == 404
    assert client.post(f"{BASE}/content/{item['id']}/approve", json={"version_id": vid}, headers=other_owner_h).status_code == 404
    assert client.get(f"{BASE}/content", headers=other_owner_h).json() == []
    assert db.query(MarketingApproval).filter_by(tenant_id=other.id).count() == 0


def test_generate_twice_is_refused_while_pending(client, ws, monkeypatch):
    calls = []
    monkeypatch.setattr("app.workers.tasks.marketing_studio.generate_content",
                        type("FakeTask", (), {"delay": staticmethod(lambda *a: calls.append(a))}))
    item = _create(client, ws["mkt_h"])
    assert client.post(f"{BASE}/content/{item['id']}/generate", json={"brief": "monsoon"}, headers=ws["mkt_h"]).status_code == 202
    r = client.post(f"{BASE}/content/{item['id']}/generate", json={}, headers=ws["mkt_h"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "generation_in_progress"
    assert len(calls) == 1 and calls[0][0] == ws["tenant"].id


def test_queue_down_marks_failed_instead_of_stuck(client, ws, monkeypatch):
    def boom(*a):
        raise ConnectionError("broker down")
    monkeypatch.setattr("app.workers.tasks.marketing_studio.generate_content",
                        type("FakeTask", (), {"delay": staticmethod(boom)}))
    item = _create(client, ws["mkt_h"])
    r = client.post(f"{BASE}/content/{item['id']}/generate", json={}, headers=ws["mkt_h"])
    assert r.status_code == 503
    got = client.get(f"{BASE}/content/{item['id']}", headers=ws["mkt_h"]).json()
    assert got["generation_status"] == "failed"


def _fake_task(monkeypatch, name, calls):
    monkeypatch.setattr(f"app.workers.tasks.marketing_studio.{name}",
                        type("FakeTask", (), {"delay": staticmethod(lambda *a: calls.append(a))}))


def test_audit_and_plan_endpoints_queue_jobs_and_validate(client, ws, monkeypatch):
    calls = []
    _fake_task(monkeypatch, "generate_audit", calls)
    _fake_task(monkeypatch, "generate_plan", calls)
    r = client.post(f"{BASE}/audits", headers=ws["mkt_h"])
    assert r.status_code == 202 and r.json()["status"] == "pending" and r.json()["measured"]["available"] is False
    audit_id = r.json()["id"]

    bad = client.post(f"{BASE}/plans", json={"period_start": "2026-11-01", "period_end": "2027-03-01"}, headers=ws["mkt_h"])
    assert bad.status_code == 422 and bad.json()["detail"]["code"] == "bad_period"
    r = client.post(f"{BASE}/plans", json={"period_start": "2026-11-01", "period_end": "2026-11-30", "audit_id": audit_id},
                    headers=ws["mkt_h"])
    assert r.status_code == 202
    assert [c[1] for c in calls] == [audit_id, r.json()["id"]]


def test_front_of_house_cannot_read_marketing(client, db, ws):
    _, foh_h = make_user(db, ws["tenant"].id, UserRole.FOH)
    assert client.get(f"{BASE}/content", headers=foh_h).status_code == 403
    assert client.post(f"{BASE}/content", json={"kind": "post", "title": "x"}, headers=foh_h).status_code == 403


def test_media_upload_endpoint(client, ws, monkeypatch):
    import io
    from PIL import Image

    monkeypatch.setattr("app.services.media_storage.upload_marketing_media", lambda t, c, m, e: f"{t}/marketing/x.{e}")
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), (200, 100, 50)).save(buf, format="JPEG")
    r = client.post(f"{BASE}/media", files={"file": ("photo.jpg", buf.getvalue(), "image/jpeg")},
                    data={"alt_text": "Caravan at dusk"}, headers=ws["mkt_h"])
    assert r.status_code == 201, r.text
    assert r.json()["mime_type"] == "image/jpeg" and r.json()["alt_text"] == "Caravan at dusk"
    r = client.post(f"{BASE}/media", files={"file": ("x.html", b"<html><script>x</script>", "text/html")}, headers=ws["mkt_h"])
    assert r.status_code == 415
