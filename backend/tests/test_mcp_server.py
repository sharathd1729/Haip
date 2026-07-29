"""MCP (Model Context Protocol) HTTP transport tests -- Perisclaw integration.

Covers: initialize handshake, auth rejection (missing/garbage/revoked
token), one read tool, one write tool, and tenant isolation (a token from
tenant A must never see tenant B's data).
"""
import uuid
from unittest.mock import patch

from tests.conftest import *  # noqa: F401,F403

from app.services import token_service


class _NoCloseSessionWrapper:
    """server.py opens its own SessionLocal() (MCP tools run outside
    FastAPI's per-request dependency cycle, same as a Celery task) --
    patch it to the test fixture's session so it sees uncommitted fixture
    data, same pattern test_webhooks_whatsapp_per_tenant_secret.py uses."""
    def __init__(self, real_session):
        self._s = real_session

    def __getattr__(self, name):
        return getattr(self._s, name)

    def close(self):
        pass


def _rpc(client, method, params=None, request_id=1, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
        headers=headers,
    )


def test_initialize_requires_no_auth(client, db):
    with patch("app.mcp.server.SessionLocal", return_value=_NoCloseSessionWrapper(db)):
        resp = _rpc(client, "initialize")
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["serverInfo"]["name"] == "haip-mcp"


def test_tools_list_rejects_missing_token(client, db):
    with patch("app.mcp.server.SessionLocal", return_value=_NoCloseSessionWrapper(db)):
        resp = _rpc(client, "tools/list")
    body = resp.json()
    assert "error" in body
    assert body["error"]["code"] == -32001


def test_tools_list_rejects_garbage_token(client, db):
    with patch("app.mcp.server.SessionLocal", return_value=_NoCloseSessionWrapper(db)):
        resp = _rpc(client, "tools/list", token="not-a-real-token")
    assert "error" in resp.json()


def test_tools_list_rejects_revoked_token(client, db, tenant_and_user):
    tenant = tenant_and_user["tenant"]
    user = tenant_and_user["user"]
    raw_token, record = token_service.generate_token(db, tenant.id, user.id, "Perisclaw")
    token_service.revoke_token(db, tenant_id=tenant.id, user_id=user.id, token_id=record.id)

    with patch("app.mcp.server.SessionLocal", return_value=_NoCloseSessionWrapper(db)):
        resp = _rpc(client, "tools/list", token=raw_token)
    assert "error" in resp.json()


def test_tools_list_returns_read_and_write_tools(client, db, tenant_and_user):
    tenant = tenant_and_user["tenant"]
    user = tenant_and_user["user"]
    raw_token, _ = token_service.generate_token(db, tenant.id, user.id, "Perisclaw")

    with patch("app.mcp.server.SessionLocal", return_value=_NoCloseSessionWrapper(db)):
        resp = _rpc(client, "tools/list", token=raw_token)
    tools = resp.json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert "list_leads" in names
    assert "move_lead_stage" in names
    # Handler must never leak into the wire response.
    assert all("handler" not in t for t in tools)


def _create_lead(db, tenant_id: str) -> str:
    from app.models.guest import Guest
    from app.models.inquiry import Inquiry, InquirySource
    from app.models.pipeline_stage import PipelineStage

    stage = PipelineStage(
        id=str(uuid.uuid4()), tenant_id=tenant_id, key="active", label="Active",
        category="valid", order=2, is_valid_lead_entry=True,
    )
    db.add(stage)
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Test Guest", phone="+919999900001")
    db.add(guest)
    db.flush()
    inquiry = Inquiry(
        id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id,
        stage_id=stage.id, source=InquirySource.PHONE,
    )
    db.add(inquiry)
    db.commit()
    return inquiry.id


def test_read_tool_list_leads(client, db, tenant_and_user):
    tenant = tenant_and_user["tenant"]
    user = tenant_and_user["user"]
    _create_lead(db, tenant.id)
    raw_token, _ = token_service.generate_token(db, tenant.id, user.id, "Perisclaw")

    with patch("app.mcp.server.SessionLocal", return_value=_NoCloseSessionWrapper(db)):
        resp = _rpc(client, "tools/call", {"name": "list_leads", "arguments": {}}, token=raw_token)
    result = resp.json()["result"]
    assert result["isError"] is False
    assert "Test Guest" in result["content"][0]["text"] or "leads" in result["content"][0]["text"]


def test_write_tool_add_note(client, db, tenant_and_user):
    tenant = tenant_and_user["tenant"]
    user = tenant_and_user["user"]
    inquiry_id = _create_lead(db, tenant.id)
    raw_token, _ = token_service.generate_token(db, tenant.id, user.id, "Perisclaw")

    with patch("app.mcp.server.SessionLocal", return_value=_NoCloseSessionWrapper(db)):
        resp = _rpc(
            client, "tools/call",
            {"name": "add_note", "arguments": {"inquiry_id": inquiry_id, "note": "Called back, follow up Monday"}},
            token=raw_token,
        )
    result = resp.json()["result"]
    assert result["isError"] is False
    assert "Called back" in result["content"][0]["text"]


def test_tenant_isolation_lead_detail_not_visible_across_tenants(client, db, tenant_and_user):
    """A PAT scoped to tenant A must not be able to read tenant B's lead,
    even by guessing/knowing its inquiry_id."""
    tenant_a = tenant_and_user["tenant"]
    user_a = tenant_and_user["user"]

    from app.models.tenant import Tenant
    tenant_b = Tenant(id=str(uuid.uuid4()), name="Tenant B", slug=f"tb-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant_b)
    db.flush()
    db.commit()
    inquiry_b_id = _create_lead(db, tenant_b.id)

    raw_token_a, _ = token_service.generate_token(db, tenant_a.id, user_a.id, "Perisclaw")

    with patch("app.mcp.server.SessionLocal", return_value=_NoCloseSessionWrapper(db)):
        resp = _rpc(
            client, "tools/call",
            {"name": "get_lead_detail", "arguments": {"inquiry_id": inquiry_b_id}},
            token=raw_token_a,
        )
    result = resp.json()["result"]
    assert result["isError"] is True
    assert "not found" in result["content"][0]["text"].lower()
