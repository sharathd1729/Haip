"""POST /knowledge/upload and POST /knowledge/crawl -- bulk KB ingestion.

Both land content as review_status="pending" (never auto-approved) and
never touch Supabase storage -- uploaded files go through media_storage.py's
existing R2-backed S3 client (mocked here; a real network call to R2 has
no place in a unit test).
"""
import io
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models.module import Module, WorkspaceModule
from app.models.capability import Capability, RoleCapability
from app.models.knowledge import KnowledgeEntry


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


@pytest.fixture()
def headers(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


def _grant_module(db, tenant_id, code="ai_concierge"):
    module = db.query(Module).filter_by(code=code).first()
    if not module:
        module = Module(id=str(uuid.uuid4()), code=code, name=code.title())
        db.add(module)
        db.flush()
    db.add(WorkspaceModule(id=str(uuid.uuid4()), workspace_id=tenant_id, module_id=module.id, enabled=True))
    db.commit()


def _grant_capability(db, tenant_id, role, key="settings.manage"):
    cap = db.query(Capability).filter_by(key=key).first()
    if not cap:
        cap = Capability(key=key, label=key, category="settings", is_write=True, risk="low")
        db.add(cap)
        db.flush()
    db.add(RoleCapability(id=str(uuid.uuid4()), tenant_id=tenant_id, role=role, capability_key=key, allowed=True))
    db.commit()


@pytest.fixture(autouse=True)
def _provision_workspace(db, tenant_and_user):
    """require_module("ai_concierge") and require_capability("settings.manage")
    both fail closed for a workspace with zero rows (CLAUDE.md's own
    documented fail-closed policy) -- tenant_and_user creates a bare Tenant
    row directly, not via /auth/register, so neither ever gets
    auto-provisioned. Every knowledge endpoint needs both."""
    tid = _tenant_id(tenant_and_user)
    _grant_module(db, tid)
    _grant_capability(db, tid, role="owner")


@pytest.fixture(autouse=True)
def _mock_embedding_dispatch():
    with patch("app.workers.tasks.embed_knowledge.embed_entry.delay", MagicMock()):
        yield


# ── POST /knowledge/upload ──────────────────────────────────────────────────

class TestUploadEndpoint:
    def test_uploading_a_text_file_creates_pending_entries(self, client, db, tenant_and_user, headers):
        with patch("app.services.media_storage.upload_knowledge_file", return_value="t1/knowledge/x/notes.txt") as mock_store:
            resp = client.post(
                "/api/v1/knowledge/upload",
                files={"file": ("notes.txt", io.BytesIO(b"Pets are welcome in all our caravans."), "text/plain")},
                headers=headers,
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["entries_created"] == 1
        assert "notes.txt" in body["message"]
        mock_store.assert_called_once()

        entry = db.query(KnowledgeEntry).filter_by(tenant_id=_tenant_id(tenant_and_user)).first()
        assert entry is not None
        assert entry.source == "document"
        assert entry.source_ref == "notes.txt"
        assert entry.file_s3_key == "t1/knowledge/x/notes.txt"
        assert entry.review_status == "pending"  # never auto-approved

    def test_rejects_unsupported_file_type(self, client, headers):
        resp = client.post(
            "/api/v1/knowledge/upload",
            files={"file": ("photo.jpg", io.BytesIO(b"\xff\xd8\xff\xe0"), "image/jpeg")},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "Unsupported file type" in resp.json()["detail"]

    def test_rejects_oversized_file(self, client, headers):
        from app.services import knowledge_ingest as ki

        big = b"x" * (ki.MAX_UPLOAD_BYTES + 1)
        resp = client.post(
            "/api/v1/knowledge/upload",
            files={"file": ("big.txt", io.BytesIO(big), "text/plain")},
            headers=headers,
        )
        assert resp.status_code == 400
        assert "too large" in resp.json()["detail"].lower()

    def test_rejects_empty_file(self, client, headers):
        resp = client.post(
            "/api/v1/knowledge/upload",
            files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")},
            headers=headers,
        )
        assert resp.status_code == 400

    def test_requires_auth(self, client):
        resp = client.post(
            "/api/v1/knowledge/upload",
            files={"file": ("notes.txt", io.BytesIO(b"content"), "text/plain")},
        )
        assert resp.status_code in (401, 403)


# ── POST /knowledge/crawl ───────────────────────────────────────────────────

class TestCrawlEndpoint:
    def test_crawling_a_url_creates_pending_entries(self, client, db, tenant_and_user, headers):
        html = "<html><body><p>Check-in is from 2pm, check-out by 11am.</p></body></html>"
        mock_resp = MagicMock(status_code=200, content=html.encode(), headers={"content-type": "text/html"}, text=html)
        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.get.return_value = mock_resp
            resp = client.post(
                "/api/v1/knowledge/crawl",
                json={"urls": ["https://example.test/faq"]},
                headers=headers,
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["entries_created"] == 1

        entry = db.query(KnowledgeEntry).filter_by(tenant_id=_tenant_id(tenant_and_user)).first()
        assert entry is not None
        assert entry.source == "website"
        assert entry.source_url == "https://example.test/faq"
        assert entry.review_status == "pending"

    def test_empty_url_list_is_422(self, client, headers):
        resp = client.post("/api/v1/knowledge/crawl", json={"urls": []}, headers=headers)
        assert resp.status_code == 422

    def test_too_many_urls_is_422(self, client, headers):
        """Enforced by KnowledgeCrawlRequest's own max_length -- rejected
        at the schema level before the endpoint body ever runs."""
        from app.services import knowledge_ingest as ki

        urls = [f"https://example.test/page{i}" for i in range(ki.MAX_URLS_PER_REQUEST + 1)]
        resp = client.post("/api/v1/knowledge/crawl", json={"urls": urls}, headers=headers)
        assert resp.status_code == 422

    def test_one_failing_url_does_not_block_the_others(self, client, db, tenant_and_user, headers):
        good_html = "<html><body><p>Free WiFi in every unit.</p></body></html>"
        good_resp = MagicMock(status_code=200, content=good_html.encode(), headers={"content-type": "text/html"}, text=good_html)
        bad_resp = MagicMock(status_code=404, content=b"", headers={"content-type": "text/html"}, text="")

        with patch("httpx.Client") as MockClient:
            MockClient.return_value.__enter__.return_value.get.side_effect = [good_resp, bad_resp]
            resp = client.post(
                "/api/v1/knowledge/crawl",
                json={"urls": ["https://example.test/good", "https://example.test/bad"]},
                headers=headers,
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["entries_created"] == 1
        assert "404" in body["message"] or "1 page(s) failed" in body["message"]

    def test_requires_auth(self, client):
        resp = client.post("/api/v1/knowledge/crawl", json={"urls": ["https://example.test/x"]})
        assert resp.status_code in (401, 403)


# ── Tenant isolation ─────────────────────────────────────────────────────────

def test_uploaded_entries_are_tenant_isolated(client, db, tenant_and_user):
    from app.models.tenant import Tenant
    from app.models.user import User, UserRole
    from app.core.security import create_access_token, get_password_hash

    other_tenant = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other_tenant); db.flush()
    other_user = User(
        id=str(uuid.uuid4()), tenant_id=other_tenant.id, name="Other Owner",
        email=f"other-{uuid.uuid4().hex[:6]}@test.com",
        hashed_password=get_password_hash("testpassword123"), role=UserRole.OWNER, is_active=True,
    )
    db.add(other_user)
    db.commit()
    _grant_module(db, other_tenant.id)
    _grant_capability(db, other_tenant.id, role="owner")
    other_headers = {"Authorization": f"Bearer {create_access_token({'sub': other_user.id, 'tenant_id': other_tenant.id, 'role': 'owner'})}"}

    with patch("app.services.media_storage.upload_knowledge_file", return_value="key"), \
         patch("app.workers.tasks.embed_knowledge.embed_entry.delay", MagicMock()):
        client.post(
            "/api/v1/knowledge/upload",
            files={"file": ("secret.txt", io.BytesIO(b"tenant A's private rate card content"), "text/plain")},
            headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
        )

    resp = client.get("/api/v1/knowledge", headers=other_headers)
    assert resp.status_code == 200
    assert all("secret" not in (e.get("source_ref") or "") for e in resp.json()["items"])
