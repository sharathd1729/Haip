"""Yaad over MCP (ChatGPT / Claude connectors): a personal workspace sees only Yaad's tools, a business workspace
never does; reads and writes stay inside the token's own workspace. Made-up data only."""

import uuid
from unittest.mock import patch

from app.models.capability import Capability
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import authz_service, token_service
from app.services import personal_calls as pc
from tests.conftest import *  # noqa: F401,F403
from tests.test_mcp_server import _NoCloseSessionWrapper, _rpc
from tests.test_personal_calls import MEMORY, _personal
from tests.workers import call_analysis_harness as h

_CAPS = [
    ("calls.read", "Calls read", "calls", False, "low"),
    ("leads.read", "Leads read", "leads", False, "low"),
    ("leads.write", "Leads write", "leads", True, "medium"),
]


def _setup(db, tenant_id, personal=True):
    for key, label, category, is_write, risk in _CAPS:
        if db.query(Capability).filter_by(key=key).first() is None:
            db.add(Capability(key=key, label=label, category=category, is_write=is_write, risk=risk))
    db.commit()
    authz_service.seed_default_capabilities(db, tenant_id)
    if personal:
        _personal(db, tenant_id)


def _memory_call(db, tenant_id):
    c = h.call(db, tenant_id, ivr_provider="mobile_app", with_transcript=False)
    pc.store(c, pc.normalise(MEMORY))
    db.commit()
    return c


def _go(client, db, token, method, params=None):
    with patch("app.mcp.server.SessionLocal", return_value=_NoCloseSessionWrapper(db)):
        return _rpc(client, method, params, token=token)


def _call(client, db, token, name, args):
    return _go(client, db, token, "tools/call", {"name": name, "arguments": args}).json()["result"]


def test_personal_workspace_gets_only_yaad_tools(client, db, tenant_and_user):
    tenant, user = tenant_and_user["tenant"], tenant_and_user["user"]
    _setup(db, tenant.id)
    token, _ = token_service.generate_token(db, tenant.id, user.id, "ChatGPT")
    init = _go(client, db, token, "initialize").json()["result"]
    assert init["serverInfo"]["title"] == "Yaad" and "phone calls" in init["instructions"]
    names = {t["name"] for t in _go(client, db, token, "tools/list").json()["result"]["tools"]}
    assert names and all(n.startswith("yaad_") for n in names)
    assert "yaad_mark_reminder_done" in names
    assert (
        _go(client, db, token, "tools/call", {"name": "list_leads", "arguments": {}}).json()["error"]["code"] == -32602
    )


def test_business_workspace_never_sees_yaad_tools(client, db, tenant_and_user):
    tenant, user = tenant_and_user["tenant"], tenant_and_user["user"]
    _setup(db, tenant.id, personal=False)
    token, _ = token_service.generate_token(db, tenant.id, user.id, "Claude")
    names = {t["name"] for t in _go(client, db, token, "tools/list").json()["result"]["tools"]}
    assert not any(n.startswith("yaad_") for n in names)
    resp = _go(client, db, token, "tools/call", {"name": "yaad_search_memories", "arguments": {}}).json()
    assert resp["error"]["code"] == -32602


def test_search_read_and_tick_a_reminder(client, db, tenant_and_user):
    tenant, user = tenant_and_user["tenant"], tenant_and_user["user"]
    _setup(db, tenant.id)
    c = _memory_call(db, tenant.id)
    token, _ = token_service.generate_token(db, tenant.id, user.id, "ChatGPT")

    found = _call(client, db, token, "yaad_search_memories", {"query": "delegation"})
    assert found["isError"] is False and c.id in found["content"][0]["text"]
    memory = _call(client, db, token, "yaad_get_memory", {"call_id": c.id})
    text = memory["content"][0]["text"]
    assert "Host the delegation" in text and "recording_url" not in text and '"transcript"' not in text

    reminder = next(a for a in pc.memory_of(c)["action_items"] if a["text"] == "Book the venue")
    args = {"call_id": c.id, "reminder_id": reminder["id"]}
    blocked = _call(client, db, token, "yaad_mark_reminder_done", args)
    assert blocked["isError"] is True and "confirm" in blocked["content"][0]["text"]
    done = _call(client, db, token, "yaad_mark_reminder_done", {**args, "confirm": True, "idempotency_key": "k1"})
    assert done["isError"] is False
    db.refresh(c)
    assert next(a for a in pc.memory_of(c)["action_items"] if a["id"] == reminder["id"])["done"] is True


def test_add_event_rejects_a_bad_month_and_adds_one(client, db, tenant_and_user):
    tenant, user = tenant_and_user["tenant"], tenant_and_user["user"]
    _setup(db, tenant.id)
    token, _ = token_service.generate_token(db, tenant.id, user.id, "ChatGPT")
    assert _call(client, db, token, "yaad_calendar", {"month": "Nov"})["isError"] is True
    added = _call(
        client,
        db,
        token,
        "yaad_add_event",
        {
            "title": "Venue walk-through",
            "day": "2099-11-20",
            "start_time": "11:00",
            "confirm": True,
            "idempotency_key": "e1",
        },
    )
    assert added["isError"] is False
    month = _call(client, db, token, "yaad_calendar", {"month": "2099-11"})
    assert "Venue walk-through" in month["content"][0]["text"]


def test_another_workspaces_call_is_not_found(client, db, tenant_and_user):
    tenant, user = tenant_and_user["tenant"], tenant_and_user["user"]
    _setup(db, tenant.id)
    other = Tenant(id=str(uuid.uuid4()), name="Other person", slug=f"me-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    _personal(db, other.id)
    theirs = _memory_call(db, other.id)
    token, _ = token_service.generate_token(db, tenant.id, user.id, "ChatGPT")
    got = _call(client, db, token, "yaad_get_memory", {"call_id": theirs.id})
    assert got["isError"] is True and "not found" in got["content"][0]["text"].lower()
    found = _call(client, db, token, "yaad_search_memories", {"query": "delegation"})
    assert theirs.id not in found["content"][0]["text"]


def test_a_non_owner_role_is_refused(client, db, tenant_and_user):
    tenant = tenant_and_user["tenant"]
    _setup(db, tenant.id)
    helper = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        email=f"h-{uuid.uuid4().hex[:6]}@example.com",
        name="Made Up Helper",
        hashed_password="x",
        role=UserRole.CONCIERGE,
        is_active=True,
    )
    db.add(helper)
    db.commit()
    token, _ = token_service.generate_token(db, tenant.id, helper.id, "ChatGPT")
    assert _go(client, db, token, "tools/list").status_code == 403


def test_discovery_points_at_the_public_mcp_address(client, db):
    with patch("app.mcp.oauth.settings.MCP_PUBLIC_URL", "https://api.example.test"):
        resp = _go(client, db, None, "initialize")
        meta = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert resp.status_code == 401
    assert 'resource_metadata="https://api.example.test/.well-known/' in resp.headers["www-authenticate"]
    assert meta["resource"] == "https://api.example.test/mcp"
