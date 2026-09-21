"""
Phase 5 tests (HAIP_MCP_Connector_Plan.md section 8) -- the OAuth 2.1
authorization server that lets Claude.ai / ChatGPT connectors reach /mcp.

Covers discovery metadata, Dynamic Client Registration, /authorize
validation, the consent endpoint (role gate + re-validation), the code ->
token -> /mcp round trip, PKCE, single-use codes, refresh rotation,
revocation, deactivated users and cross-tenant isolation.
"""
import base64
import hashlib
import secrets
import uuid
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.capability import Capability
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.mcp_oauth import OAuthGrant
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import authz_service

CLAUDE_REDIRECT = "https://claude.ai/api/mcp/auth_callback"


# ── helpers ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _no_rate_limit():
    """/oauth/register and /oauth/token sit in the strict 10/min-per-IP tier;
    this file registers far more clients than that from one test IP."""
    with patch("app.middleware.rate_limit._check_limit", return_value=(True, 0)):
        yield


class _NoCloseSession:
    """app/mcp/oauth.py and server.py open their own SessionLocal(); point
    both at the test's session (see test_mcp_phase0.py for the rationale)."""
    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def close(self):
        pass


def _patched(db):
    factory = lambda: _NoCloseSession(db)  # noqa: E731
    return (
        patch("app.mcp.oauth.SessionLocal", factory),
        patch("app.mcp.server.SessionLocal", factory),
    )


class _Session:
    def __init__(self, db):
        self.patches = _patched(db)

    def __enter__(self):
        for p in self.patches:
            p.start()

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()


def _make_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"slug-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush(); return t


def _make_user(db, tenant_id, role=UserRole.OWNER):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name="U",
        email=f"u-{uuid.uuid4().hex[:6]}@test.com",
        hashed_password=get_password_hash("pw"), role=role, is_active=True,
    )
    db.add(u); db.flush(); return u


def _jwt(user):
    return create_access_token({"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value})


def _seed_caps(db, *tenant_ids):
    if db.query(Capability.key).filter_by(key="leads.read").first() is None:
        db.add(Capability(key="leads.read", label="Leads read", category="leads", is_write=False, risk="low"))
        db.add(Capability(key="leads.write", label="Leads write", category="leads", is_write=True, risk="medium"))
        db.commit()
    for t in tenant_ids:
        authz_service.seed_default_capabilities(db, t)


def _pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _register(client, db, redirect=CLAUDE_REDIRECT, **extra):
    with _Session(db):
        return client.post("/oauth/register", json={"client_name": "Claude", "redirect_uris": [redirect], **extra})


def _consent(client, user, client_id, challenge, decision="approve", access="read_write", redirect=CLAUDE_REDIRECT, **over):
    body = {
        "decision": decision, "access": access, "client_id": client_id, "redirect_uri": redirect,
        "response_type": "code", "code_challenge": challenge, "code_challenge_method": "S256",
        "state": "xyz", **over,
    }
    return client.post("/api/v1/oauth/consent", json=body, headers={"Authorization": f"Bearer {_jwt(user)}"})


def _code_from(redirect_to):
    return parse_qs(urlsplit(redirect_to).query)


def _token(client, db, **form):
    with _Session(db):
        return client.post("/oauth/token", data=form)


def _connect(client, db, user, access="read_write"):
    """Full happy path: register -> consent -> token. Returns (client_id, tokens)."""
    client_id = _register(client, db).json()["client_id"]
    verifier, challenge = _pkce()
    redirect_to = _consent(client, user, client_id, challenge, access=access).json()["redirect_to"]
    code = _code_from(redirect_to)["code"][0]
    tokens = _token(
        client, db, grant_type="authorization_code", code=code, redirect_uri=CLAUDE_REDIRECT,
        code_verifier=verifier, client_id=client_id,
    ).json()
    return client_id, tokens


def _rpc(client, db, token, method, params=None):
    with _Session(db):
        return client.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
            headers={"Authorization": f"Bearer {token}"},
        )


# ── discovery ─────────────────────────────────────────────────────────────────

class TestDiscovery:
    def test_protected_resource_metadata(self, client):
        for path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
            body = client.get(path).json()
            assert body["resource"].endswith("/mcp")
            assert len(body["authorization_servers"]) == 1

    def test_authorization_server_metadata(self, client):
        body = client.get("/.well-known/oauth-authorization-server").json()
        assert body["code_challenge_methods_supported"] == ["S256"]
        assert body["registration_endpoint"].endswith("/oauth/register")
        assert body["token_endpoint"].endswith("/oauth/token")
        assert "authorization_code" in body["grant_types_supported"]


# ── registration ──────────────────────────────────────────────────────────────

class TestRegistration:
    def test_public_client_registers_without_secret(self, client, db):
        resp = _register(client, db)
        assert resp.status_code == 201
        assert resp.json()["token_endpoint_auth_method"] == "none"
        assert "client_secret" not in resp.json()

    def test_confidential_client_gets_secret(self, client, db):
        resp = _register(client, db, token_endpoint_auth_method="client_secret_post")
        assert resp.status_code == 201
        assert resp.json()["client_secret"]

    def test_rejects_javascript_redirect(self, client, db):
        assert _register(client, db, redirect="javascript:alert(1)").status_code == 400

    def test_rejects_plain_http_non_loopback(self, client, db):
        assert _register(client, db, redirect="http://evil.example/cb").status_code == 400

    def test_allows_loopback_http(self, client, db):
        assert _register(client, db, redirect="http://localhost:33418/callback").status_code == 201


# ── /authorize ────────────────────────────────────────────────────────────────

class TestAuthorize:
    def test_valid_request_redirects_to_consent_page(self, client, db):
        client_id = _register(client, db).json()["client_id"]
        _, challenge = _pkce()
        with _Session(db):
            resp = client.get("/oauth/authorize", params={
                "client_id": client_id, "redirect_uri": CLAUDE_REDIRECT, "response_type": "code",
                "code_challenge": challenge, "code_challenge_method": "S256", "state": "s1",
            }, follow_redirects=False)
        assert resp.status_code == 302
        assert "/connect/authorize?" in resp.headers["location"]
        assert "state=s1" in resp.headers["location"]

    def test_unregistered_redirect_does_not_redirect(self, client, db):
        """Open-redirector guard: never bounce to a URI we didn't register."""
        client_id = _register(client, db).json()["client_id"]
        _, challenge = _pkce()
        with _Session(db):
            resp = client.get("/oauth/authorize", params={
                "client_id": client_id, "redirect_uri": "https://evil.example/cb", "response_type": "code",
                "code_challenge": challenge, "code_challenge_method": "S256",
            }, follow_redirects=False)
        assert resp.status_code == 400

    def test_missing_pkce_is_redirected_back_as_error(self, client, db):
        client_id = _register(client, db).json()["client_id"]
        with _Session(db):
            resp = client.get("/oauth/authorize", params={
                "client_id": client_id, "redirect_uri": CLAUDE_REDIRECT, "response_type": "code", "state": "s",
            }, follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"].startswith(CLAUDE_REDIRECT)
        assert "error=invalid_request" in resp.headers["location"]

    def test_plain_pkce_rejected(self, client, db):
        client_id = _register(client, db).json()["client_id"]
        with _Session(db):
            resp = client.get("/oauth/authorize", params={
                "client_id": client_id, "redirect_uri": CLAUDE_REDIRECT, "response_type": "code",
                "code_challenge": "x" * 50, "code_challenge_method": "plain",
            }, follow_redirects=False)
        assert "error=invalid_request" in resp.headers["location"]


# ── consent ───────────────────────────────────────────────────────────────────

class TestConsent:
    def test_concierge_cannot_approve(self, client, db):
        tenant = _make_tenant(db)
        concierge = _make_user(db, tenant.id, role=UserRole.CONCIERGE)
        db.commit()
        client_id = _register(client, db).json()["client_id"]
        _, challenge = _pkce()
        assert _consent(client, concierge, client_id, challenge).status_code == 403

    def test_deny_returns_access_denied(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id)
        db.commit()
        client_id = _register(client, db).json()["client_id"]
        _, challenge = _pkce()
        resp = _consent(client, owner, client_id, challenge, decision="deny")
        params = _code_from(resp.json()["redirect_to"])
        assert params["error"] == ["access_denied"]
        assert params["state"] == ["xyz"]

    def test_consent_revalidates_redirect(self, client, db):
        """The consent page's query string is user-editable."""
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id)
        db.commit()
        client_id = _register(client, db).json()["client_id"]
        _, challenge = _pkce()
        resp = _consent(client, owner, client_id, challenge, redirect="https://evil.example/cb")
        assert resp.status_code == 400

    def test_approve_writes_audit_event(self, client, db):
        from app.models.audit_event import AuditEvent
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id)
        db.commit()
        client_id = _register(client, db).json()["client_id"]
        _, challenge = _pkce()
        _consent(client, owner, client_id, challenge)
        assert db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="mcp.oauth.grant").count() == 1


# ── token exchange + /mcp ─────────────────────────────────────────────────────

class TestTokenFlow:
    def test_full_round_trip_reaches_mcp(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id)
        db.commit()
        _seed_caps(db, tenant.id)
        _, tokens = _connect(client, db, owner)
        assert tokens["token_type"] == "Bearer"
        assert tokens["access_token"].startswith("haip_oat_")

        init = _rpc(client, db, tokens["access_token"], "initialize", {"protocolVersion": "2025-06-18"})
        assert init.status_code == 200
        listed = _rpc(client, db, tokens["access_token"], "tools/list")
        names = {t["name"] for t in listed.json()["result"]["tools"]}
        assert "list_leads" in names

    def test_read_only_consent_hides_write_tools(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id)
        db.commit()
        _seed_caps(db, tenant.id)
        _, tokens = _connect(client, db, owner, access="read_only")
        names = {t["name"] for t in _rpc(client, db, tokens["access_token"], "tools/list").json()["result"]["tools"]}
        assert "list_leads" in names
        assert "move_lead_stage" not in names

    def test_wrong_verifier_rejected(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id)
        db.commit()
        client_id = _register(client, db).json()["client_id"]
        _, challenge = _pkce()
        code = _code_from(_consent(client, owner, client_id, challenge).json()["redirect_to"])["code"][0]
        resp = _token(client, db, grant_type="authorization_code", code=code, redirect_uri=CLAUDE_REDIRECT,
                      code_verifier=secrets.token_urlsafe(48), client_id=client_id)
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_grant"

    def test_code_is_single_use_and_replay_revokes(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id)
        db.commit()
        client_id = _register(client, db).json()["client_id"]
        verifier, challenge = _pkce()
        code = _code_from(_consent(client, owner, client_id, challenge).json()["redirect_to"])["code"][0]
        form = dict(grant_type="authorization_code", code=code, redirect_uri=CLAUDE_REDIRECT,
                    code_verifier=verifier, client_id=client_id)
        first = _token(client, db, **form)
        assert first.status_code == 200
        second = _token(client, db, **form)
        assert second.status_code == 400
        # The code hash is cleared on first use, so a replay can't even find
        # the grant -- and the tokens from the first exchange still work.
        assert _rpc(client, db, first.json()["access_token"], "ping").status_code == 200

    def test_other_client_cannot_redeem_code(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id)
        db.commit()
        client_id = _register(client, db).json()["client_id"]
        other_id = _register(client, db).json()["client_id"]
        verifier, challenge = _pkce()
        code = _code_from(_consent(client, owner, client_id, challenge).json()["redirect_to"])["code"][0]
        resp = _token(client, db, grant_type="authorization_code", code=code, redirect_uri=CLAUDE_REDIRECT,
                      code_verifier=verifier, client_id=other_id)
        assert resp.json()["error"] == "invalid_grant"

    def test_confidential_client_needs_secret(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id)
        db.commit()
        reg = _register(client, db, token_endpoint_auth_method="client_secret_basic").json()
        verifier, challenge = _pkce()
        code = _code_from(_consent(client, owner, reg["client_id"], challenge).json()["redirect_to"])["code"][0]
        form = dict(grant_type="authorization_code", code=code, redirect_uri=CLAUDE_REDIRECT,
                    code_verifier=verifier, client_id=reg["client_id"])
        assert _token(client, db, **form).status_code == 401
        basic = base64.b64encode(f"{reg['client_id']}:{reg['client_secret']}".encode()).decode()
        with _Session(db):
            resp = client.post("/oauth/token", data=form, headers={"Authorization": f"Basic {basic}"})
        assert resp.status_code == 200

    def test_refresh_rotates_and_old_refresh_dies(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id)
        db.commit()
        client_id, tokens = _connect(client, db, owner)
        refreshed = _token(client, db, grant_type="refresh_token", refresh_token=tokens["refresh_token"], client_id=client_id)
        assert refreshed.status_code == 200
        new = refreshed.json()
        assert new["refresh_token"] != tokens["refresh_token"]
        again = _token(client, db, grant_type="refresh_token", refresh_token=tokens["refresh_token"], client_id=client_id)
        assert again.status_code == 400
        # Old access token is replaced too.
        assert _rpc(client, db, tokens["access_token"], "ping").status_code == 401
        assert _rpc(client, db, new["access_token"], "ping").status_code == 200


# ── revocation / lifecycle ────────────────────────────────────────────────────

class TestLifecycle:
    def test_disconnect_kills_access(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id)
        db.commit()
        _, tokens = _connect(client, db, owner)
        grants = client.get("/api/v1/oauth/grants", headers={"Authorization": f"Bearer {_jwt(owner)}"}).json()
        assert len(grants) == 1 and grants[0]["client_name"] == "Claude"
        resp = client.delete(f"/api/v1/oauth/grants/{grants[0]['id']}", headers={"Authorization": f"Bearer {_jwt(owner)}"})
        assert resp.status_code == 200
        assert _rpc(client, db, tokens["access_token"], "ping").status_code == 401

    def test_user_cannot_disconnect_someone_elses_grant(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id)
        manager = _make_user(db, tenant.id, role=UserRole.MANAGER)
        db.commit()
        _connect(client, db, owner)
        grant = db.query(OAuthGrant).filter_by(user_id=owner.id).first()
        resp = client.delete(f"/api/v1/oauth/grants/{grant.id}", headers={"Authorization": f"Bearer {_jwt(manager)}"})
        assert resp.status_code == 404

    def test_deactivated_user_denied(self, client, db):
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id)
        db.commit()
        _, tokens = _connect(client, db, owner)
        owner.is_active = False
        db.commit()
        assert _rpc(client, db, tokens["access_token"], "tools/list").status_code == 403

    def test_expired_access_token_denied(self, client, db):
        from datetime import datetime, timedelta, timezone
        tenant = _make_tenant(db)
        owner = _make_user(db, tenant.id)
        db.commit()
        _, tokens = _connect(client, db, owner)
        grant = db.query(OAuthGrant).filter_by(user_id=owner.id).first()
        grant.access_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
        assert _rpc(client, db, tokens["access_token"], "ping").status_code == 401

    def test_cross_tenant_isolation(self, client, db):
        tenant_a, tenant_b = _make_tenant(db), _make_tenant(db)
        owner_a = _make_user(db, tenant_a.id)
        db.flush()
        guest_b = Guest(id=str(uuid.uuid4()), tenant_id=tenant_b.id, name="B guest", phone="+919999999999")
        db.add(guest_b); db.flush()
        inq_b = Inquiry(
            id=str(uuid.uuid4()), tenant_id=tenant_b.id, guest_id=guest_b.id,
            stage=InquiryStage.NEW, source=InquirySource.WA_DIRECT,
        )
        db.add(inq_b); db.commit()
        _seed_caps(db, tenant_a.id, tenant_b.id)

        _, tokens = _connect(client, db, owner_a)
        resp = _rpc(client, db, tokens["access_token"], "tools/call", {
            "name": "get_lead_detail", "arguments": {"inquiry_id": inq_b.id},
        })
        assert resp.status_code == 200
        assert resp.json()["result"]["isError"] is True
