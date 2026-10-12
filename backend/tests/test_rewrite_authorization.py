"""Authorization of the two AI-rewrite POST endpoints.

Both endpoints queue a real LLM request (NVIDIA NIM), so they are gated by the same capability as sending a
message, ``conversations.send`` (default grants: owner, manager, reservations, concierge). Before this gate they
only required a valid login and a conversation in the caller's own tenant, so a read_only, foh, marketing or
compliance user could spend provider credit.

What is pinned here:
  * the default roles that may and may not queue a rewrite, on both endpoints;
  * a denied caller gets 403 BEFORE any lookup (no "does this conversation exist" oracle) and nothing is queued;
  * the gate follows the tenant's own role matrix, not a hard-coded role list, and fails closed for a tenant that
    has no matrix at all;
  * tenant isolation is unchanged (another tenant's conversation is still a 404);
  * an unauthenticated caller is rejected.
The Celery ``.delay`` calls are patched, so no task is queued and no provider is contacted.
"""
import uuid
from unittest.mock import patch

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.capability import Capability, RoleCapability
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import authz_service

ALLOWED_ROLES = [UserRole.OWNER, UserRole.MANAGER, UserRole.RESERVATIONS, UserRole.CONCIERGE]
DENIED_ROLES = [UserRole.FOH, UserRole.MARKETING, UserRole.COMPLIANCE, UserRole.READ_ONLY]

DRAFT_DELAY = "app.workers.tasks.rewrite_draft.rewrite_draft.delay"
COMPOSER_DELAY = "app.workers.tasks.composer_rewrite.composer_rewrite.delay"


# ── helpers ────────────────────────────────────────────────────────────────────────────────────────────────

def _tenant(db, provisioned=True):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"rw-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(t); db.flush()
    if provisioned:
        # SQLite starts with an empty capability catalogue; PostgreSQL built by alembic already has the real one.
        if db.query(Capability).filter_by(key="conversations.send").first() is None:
            db.add(Capability(key="conversations.send", label="Send guest-facing messages",
                              category="conversations", is_write=True, risk="medium"))
            db.flush()
        authz_service.seed_default_capabilities(db, t.id)
    db.commit()
    return t


def _user(db, tenant_id, role):
    u = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name=f"{role.value} user",
             email=f"{role.value}-{uuid.uuid4().hex[:6]}@test.com",
             hashed_password=get_password_hash("pw"), role=role, is_active=True)
    db.add(u); db.commit()
    return u


def _headers(user):
    token = create_access_token({"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value})
    return {"Authorization": f"Bearer {token}"}


def _conversation(db, tenant_id, pending_draft=False):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Guest", phone=f"+9199990{uuid.uuid4().hex[:5]}")
    db.add(guest); db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id,
                        channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv); db.flush()
    msg = None
    if pending_draft:
        msg = Message(id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id, direction="outbound",
                      channel="whatsapp", body="The villa is free those dates!", is_ai_generated=True, was_approved=None)
        db.add(msg)
    db.commit()
    return conv, msg


def _post_draft(client, db, caller, target_tenant_id):
    conv, msg = _conversation(db, target_tenant_id, pending_draft=True)
    with patch(DRAFT_DELAY) as delay:
        resp = client.post(f"/api/v1/conversations/{conv.id}/messages/{msg.id}/rewrite",
                           json={"tone": "brief"}, headers=_headers(caller))
    return resp, delay


def _post_composer(client, db, caller, target_tenant_id):
    conv, _ = _conversation(db, target_tenant_id)
    with patch(COMPOSER_DELAY) as delay:
        resp = client.post(f"/api/v1/conversations/{conv.id}/composer/rewrite",
                           json={"text": "hi is it free", "tone": "formal"}, headers=_headers(caller))
    return resp, delay


def _post_draft_unknown(client, caller):
    with patch(DRAFT_DELAY) as delay:
        resp = client.post(f"/api/v1/conversations/{uuid.uuid4()}/messages/{uuid.uuid4()}/rewrite",
                           json={"tone": "brief"}, headers=_headers(caller))
    return resp, delay


def _post_composer_unknown(client, caller):
    with patch(COMPOSER_DELAY) as delay:
        resp = client.post(f"/api/v1/conversations/{uuid.uuid4()}/composer/rewrite",
                           json={"text": "hi"}, headers=_headers(caller))
    return resp, delay


ENDPOINTS = pytest.mark.parametrize("post", [_post_draft, _post_composer], ids=["draft", "composer"])
UNKNOWN_TARGET = pytest.mark.parametrize("post_unknown", [_post_draft_unknown, _post_composer_unknown],
                                         ids=["draft", "composer"])


# ── the default matrix ─────────────────────────────────────────────────────────────────────────────────────

@ENDPOINTS
@pytest.mark.parametrize("role", ALLOWED_ROLES, ids=lambda r: r.value)
def test_roles_that_may_send_can_queue_a_rewrite(client, db, post, role):
    tenant = _tenant(db)
    resp, delay = post(client, db, _user(db, tenant.id, role), tenant.id)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "rewrite_queued"
    delay.assert_called_once()


@ENDPOINTS
@pytest.mark.parametrize("role", DENIED_ROLES, ids=lambda r: r.value)
def test_roles_that_may_not_send_are_refused_and_nothing_is_queued(client, db, post, role):
    tenant = _tenant(db)
    resp, delay = post(client, db, _user(db, tenant.id, role), tenant.id)
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Insufficient permissions"
    delay.assert_not_called()


@UNKNOWN_TARGET
@pytest.mark.parametrize("role", DENIED_ROLES, ids=lambda r: r.value)
def test_denied_before_lookup_so_a_missing_target_is_not_revealed(client, db, post_unknown, role):
    """A caller without the capability gets 403 whether or not the conversation exists (never 404)."""
    tenant = _tenant(db)
    resp, delay = post_unknown(client, _user(db, tenant.id, role))
    assert resp.status_code == 403, resp.text
    delay.assert_not_called()


@UNKNOWN_TARGET
def test_an_allowed_role_still_gets_404_for_a_missing_target(client, db, post_unknown):
    tenant = _tenant(db)
    resp, delay = post_unknown(client, _user(db, tenant.id, UserRole.OWNER))
    assert resp.status_code == 404, resp.text
    delay.assert_not_called()


# ── the gate follows the tenant's own matrix ───────────────────────────────────────────────────────────────

@ENDPOINTS
def test_a_tenant_without_a_capability_matrix_fails_closed(client, db, post):
    """No role_capabilities rows means "unprovisioned": nobody is allowed, not even the owner."""
    tenant = _tenant(db, provisioned=False)
    resp, delay = post(client, db, _user(db, tenant.id, UserRole.OWNER), tenant.id)
    assert resp.status_code == 403, resp.text
    delay.assert_not_called()


@ENDPOINTS
def test_a_tenant_can_revoke_the_capability_from_a_default_role(client, db, post):
    tenant = _tenant(db)
    db.query(RoleCapability).filter_by(tenant_id=tenant.id, role="concierge",
                                       capability_key="conversations.send").update({"allowed": False})
    db.commit()
    resp, delay = post(client, db, _user(db, tenant.id, UserRole.CONCIERGE), tenant.id)
    assert resp.status_code == 403, resp.text
    delay.assert_not_called()


@ENDPOINTS
def test_a_tenant_can_grant_the_capability_to_another_role(client, db, post):
    tenant = _tenant(db)
    db.query(RoleCapability).filter_by(tenant_id=tenant.id, role="foh",
                                       capability_key="conversations.send").update({"allowed": True})
    db.commit()
    resp, delay = post(client, db, _user(db, tenant.id, UserRole.FOH), tenant.id)
    assert resp.status_code == 200, resp.text
    delay.assert_called_once()


@ENDPOINTS
def test_one_tenants_grant_does_not_leak_to_another_tenant(client, db, post):
    granted, other = _tenant(db), _tenant(db)
    db.query(RoleCapability).filter_by(tenant_id=granted.id, role="read_only",
                                       capability_key="conversations.send").update({"allowed": True})
    db.commit()
    resp, delay = post(client, db, _user(db, other.id, UserRole.READ_ONLY), other.id)
    assert resp.status_code == 403, resp.text
    delay.assert_not_called()


# ── tenant isolation and authentication are unchanged ──────────────────────────────────────────────────────

@ENDPOINTS
def test_another_tenants_conversation_is_still_a_404(client, db, post):
    mine, theirs = _tenant(db), _tenant(db)
    resp, delay = post(client, db, _user(db, mine.id, UserRole.OWNER), theirs.id)
    assert resp.status_code == 404, resp.text
    delay.assert_not_called()


def test_unauthenticated_requests_are_rejected(client, db):
    tenant = _tenant(db)
    conv, msg = _conversation(db, tenant.id, pending_draft=True)
    with patch(DRAFT_DELAY) as draft_delay, patch(COMPOSER_DELAY) as composer_delay:
        r1 = client.post(f"/api/v1/conversations/{conv.id}/messages/{msg.id}/rewrite", json={"tone": "brief"})
        r2 = client.post(f"/api/v1/conversations/{conv.id}/composer/rewrite", json={"text": "hi"})
    assert r1.status_code in (401, 403) and r2.status_code in (401, 403)
    draft_delay.assert_not_called()
    composer_delay.assert_not_called()
