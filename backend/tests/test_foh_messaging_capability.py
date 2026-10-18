"""Front-of-house (foh) staff reply to guests and use the AI rewrite buttons (policy, Oct 2026).

What is pinned here:
  * capability policy: foh holds ``conversations.send`` by default, nothing else about the defaults changed, and
    tenants are provisioned independently of each other;
  * migration 119, which is how the grant reaches EXISTING tenants (defaults only reach new ones): it grants foh,
    keeps a tenant owner's deliberate revocation, leaves every other cell alone, and is idempotent;
  * every route that sends to a guest (send_message, send_template, retry, approve) requires ``conversations.send``
    on the server: allowed roles send, the others get 403 and NOTHING happens (no message row, no delivery task),
    the check runs before the conversation is looked up, and tenant isolation and idempotency are unchanged.
The rewrite endpoints are covered in test_rewrite_authorization.py. Celery ``.delay`` calls are patched, so no message
is delivered and no provider is contacted. Runs on whatever database DATABASE_URL points at (SQLite locally,
PostgreSQL in CI); nothing in it is PostgreSQL-specific.
"""
import importlib.util
import pathlib
import uuid
from contextlib import ExitStack
from unittest.mock import patch

import pytest

from app.api.v1.endpoints.messaging import TemplateStatus, WATemplate
from app.core.security import create_access_token, get_password_hash
from app.models.audit_event import AuditEvent
from app.models.capability import Capability, RoleCapability
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import authz_service

# The default grants as committed before this change (every capability key -> the roles that held it).
PREVIOUS = {
    "leads.read": ['concierge', 'foh', 'manager', 'marketing', 'owner', 'read_only', 'reservations'],
    "leads.write": ['concierge', 'manager', 'owner', 'reservations'],
    "leads.merge": ['manager', 'owner'],
    "conversations.read": ['concierge', 'foh', 'manager', 'owner', 'read_only', 'reservations'],
    "conversations.send": ['concierge', 'manager', 'owner', 'reservations'],
    "calls.read": ['concierge', 'manager', 'marketing', 'owner', 'read_only', 'reservations'],
    "calls.transcript.read": ['compliance', 'concierge', 'manager', 'owner', 'reservations'],
    "calls.recording.read": ['compliance', 'manager', 'owner'],
    "guests.read": ['compliance', 'concierge', 'foh', 'manager', 'marketing', 'owner', 'read_only', 'reservations'],
    "guests.pii.reveal": ['compliance', 'concierge', 'manager', 'owner', 'reservations'],
    "bookings.read": ['concierge', 'foh', 'manager', 'owner', 'read_only', 'reservations'],
    "revenue.read": ['manager', 'marketing', 'owner'],
    "analytics.read": ['concierge', 'foh', 'manager', 'marketing', 'owner', 'read_only', 'reservations'],
    "qa.read": ['compliance', 'concierge', 'manager', 'owner', 'read_only'],
    "qa.override": ['manager', 'owner'],
    "compliance.export": ['compliance', 'owner'],
    "users.read": ['compliance', 'manager', 'owner'],
    "users.manage": ['owner'],
    "settings.manage": ['owner'],
}
ALL_ROLES = list(authz_service._ROLES)
SENDERS = [UserRole.OWNER, UserRole.MANAGER, UserRole.RESERVATIONS, UserRole.CONCIERGE, UserRole.FOH]
NON_SENDERS = [UserRole.MARKETING, UserRole.COMPLIANCE, UserRole.READ_ONLY]
CELL = ("foh", "conversations.send")


# ── helpers ────────────────────────────────────────────────────────────────────────────────────────────────

def _catalogue(db):
    for key in PREVIOUS:
        if db.query(Capability).filter_by(key=key).first() is None:
            db.add(Capability(key=key, label=key, category=key.split(".")[0], is_write=False, risk="low"))
    db.commit()


def _tenant(db, provisioned=True):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"foh-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(t); db.flush()
    if provisioned:
        _catalogue(db)
        authz_service.seed_default_capabilities(db, t.id)
    db.commit()
    return t


def _user(db, tenant_id, role):
    u = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name=f"{role.value} user",
             email=f"{role.value}-{uuid.uuid4().hex[:6]}@test.com",
             hashed_password=get_password_hash("pw"), role=role, is_active=True)
    db.add(u); db.commit()
    return u


def _headers(user, extra=None):
    token = create_access_token({"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value})
    return {"Authorization": f"Bearer {token}", **(extra or {})}


def _set_cell(db, tenant_id, role, key, allowed):
    db.query(RoleCapability).filter_by(tenant_id=tenant_id, role=role, capability_key=key).update({"allowed": allowed})
    db.commit()


def _grid(db, tenant_id):
    return {(r.role, r.capability_key): r.allowed for r in db.query(RoleCapability).filter_by(tenant_id=tenant_id)}


# ── capability policy ──────────────────────────────────────────────────────────────────────────────────────

def test_foh_is_a_default_holder_and_nothing_else_about_the_defaults_changed():
    expected = {k: list(v) for k, v in PREVIOUS.items()}
    expected["conversations.send"] = sorted(expected["conversations.send"] + ["foh"])
    # Keys added later (quotes.write, business_data.* -- migration 140) are pinned by their own tests.
    assert {k: sorted(v) for k, v in authz_service._DEFAULT_GRANTS.items() if k in PREVIOUS} == expected


def test_a_newly_provisioned_tenant_lets_foh_send_and_every_other_cell_is_as_before(db):
    grid = _grid(db, _tenant(db).id)
    grid = {cell: allowed for cell, allowed in grid.items() if cell[1] in PREVIOUS}
    assert grid[CELL] is True
    assert len(grid) == len(ALL_ROLES) * len(PREVIOUS)
    for (role, key), allowed in grid.items():
        if (role, key) != CELL:
            assert allowed == (role in PREVIOUS[key]), (role, key)
    for role in ("marketing", "compliance", "read_only"):
        assert grid[(role, "conversations.send")] is False


def test_tenants_are_provisioned_independently(db):
    a, b = _tenant(db), _tenant(db)
    _set_cell(db, a.id, *CELL, False)
    assert _grid(db, a.id)[CELL] is False
    assert _grid(db, b.id)[CELL] is True


# ── migration 119: how the grant reaches existing tenants ──────────────────────────────────────────────────

MIGRATION = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "119_foh_conversations_send.py"


@pytest.fixture(scope="module")
def mig():
    spec = importlib.util.spec_from_file_location("mig119", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _owner_edit(db, tenant_id, edits):
    db.add(AuditEvent(id=str(uuid.uuid4()), tenant_id=tenant_id, action="role_capabilities.change",
                      target_type="role_capabilities", target_id=tenant_id, payload={"edits": edits}, hash="h"))
    db.commit()


def _old_tenant(db, foh_send=False):
    """A tenant as seeded before the policy: foh denied conversations.send."""
    t = _tenant(db)
    _set_cell(db, t.id, *CELL, foh_send)
    return t


@pytest.fixture()
def world(db):
    w = {
        "default": _old_tenant(db),                      # untouched since seeding -> granted
        "custom": _old_tenant(db),                       # owner deliberately set foh = denied -> preserved
        "already": _old_tenant(db, foh_send=True),       # already allowed -> unchanged
        "missing": _old_tenant(db),                      # matrix cell absent -> inserted
        "other_edit": _old_tenant(db),                   # owner edited a DIFFERENT cell -> still granted
        "junk": _old_tenant(db),                         # unusable audit payloads -> still granted
        "unprovisioned": _tenant(db, provisioned=False), # no matrix at all -> untouched, fails closed
    }
    _owner_edit(db, w["custom"].id, [{"role": "foh", "capability_key": "conversations.send", "allowed": False}])
    _owner_edit(db, w["other_edit"].id, [{"role": "marketing", "capability_key": "leads.read", "allowed": False}])
    db.add(AuditEvent(id=str(uuid.uuid4()), tenant_id=w["junk"].id, action="role_capabilities.change", payload=None, hash="h"))
    db.add(AuditEvent(id=str(uuid.uuid4()), tenant_id=w["junk"].id, action="role_capabilities.change",
                      payload={"edits": "not-a-list"}, hash="h"))
    db.query(RoleCapability).filter_by(tenant_id=w["missing"].id, role="foh", capability_key="conversations.send").delete()
    db.commit()
    return w


def _everything_except_the_foh_cell(db, world):
    return {name: {c: v for c, v in _grid(db, t.id).items() if c != CELL} for name, t in world.items()}


def test_migration_grants_default_tenants_and_keeps_deliberate_revocations(db, mig, world):
    before = _everything_except_the_foh_cell(db, world)
    result = mig.apply_grant(db.connection())
    db.expire_all()

    assert _grid(db, world["default"].id)[CELL] is True
    assert _grid(db, world["other_edit"].id)[CELL] is True
    assert _grid(db, world["junk"].id)[CELL] is True
    assert _grid(db, world["already"].id)[CELL] is True
    assert _grid(db, world["missing"].id)[CELL] is True              # inserted
    assert _grid(db, world["custom"].id)[CELL] is False              # the owner's choice is kept
    assert _grid(db, world["unprovisioned"].id) == {}                # still no matrix: still fails closed
    assert result == {"granted": 3, "inserted": 1, "preserved_customised": 1, "skipped_no_catalogue": 0}
    # no other role or capability changed, in any tenant
    assert _everything_except_the_foh_cell(db, world) == before


def test_migration_is_idempotent(db, mig, world):
    mig.apply_grant(db.connection())
    db.expire_all()
    after_first = {n: _grid(db, t.id) for n, t in world.items()}
    again = mig.apply_grant(db.connection())
    db.expire_all()
    assert again["granted"] == 0 and again["inserted"] == 0
    assert {n: _grid(db, t.id) for n, t in world.items()} == after_first


def test_one_tenants_audit_history_does_not_protect_another_tenant(db, mig):
    protected, other = _old_tenant(db), _old_tenant(db)
    _owner_edit(db, protected.id, [{"role": "foh", "capability_key": "conversations.send", "allowed": False}])
    mig.apply_grant(db.connection())
    db.expire_all()
    assert _grid(db, protected.id)[CELL] is False
    assert _grid(db, other.id)[CELL] is True


def test_migration_does_nothing_when_the_capability_is_not_in_the_catalogue(db, mig, world, monkeypatch):
    monkeypatch.setattr(mig, "CAPABILITY", "no.such.capability")
    before = {n: _grid(db, t.id) for n, t in world.items()}
    assert mig.apply_grant(db.connection())["skipped_no_catalogue"] == 1
    db.expire_all()
    assert {n: _grid(db, t.id) for n, t in world.items()} == before


def test_migration_chain_and_downgrade():
    spec = importlib.util.spec_from_file_location("mig119b", MIGRATION)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    assert module.revision == "119" and module.down_revision == "117"
    assert module.downgrade() is None                                  # marker move only
    source = MIGRATION.read_text(encoding="utf-8")
    assert "from app" not in source and "import app" not in source     # a migration is a frozen snapshot


# ── every guest-facing send route is gated by conversations.send ───────────────────────────────────────────

DELIVERY = {
    "whatsapp": "app.workers.tasks.send_whatsapp.send_whatsapp.delay",
    "instagram": "app.workers.tasks.send_instagram_dm.send_instagram_dm.delay",
    "template": "app.workers.tasks.send_whatsapp.send_whatsapp_template.delay",
}


class _Delivery:
    """Patches every delivery task; ``fired`` is how many were enqueued in total."""
    def __enter__(self):
        self._stack = ExitStack()
        self.mocks = {k: self._stack.enter_context(patch(path)) for k, path in DELIVERY.items()}
        return self

    def __exit__(self, *exc):
        self._stack.close()

    @property
    def fired(self):
        return sum(m.call_count for m in self.mocks.values())


def _conversation(db, tenant_id):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Guest", phone=f"+91999{uuid.uuid4().int % 10**7:07d}")
    db.add(guest); db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id,
                        channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv); db.commit()
    return conv


def _message(db, tenant_id, conv_id, **kw):
    msg = Message(id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv_id, direction="outbound",
                  channel="whatsapp", body="Draft reply text", **kw)
    db.add(msg); db.commit()
    return msg


def _template(db, tenant_id):
    t = WATemplate(id=str(uuid.uuid4()), tenant_id=tenant_id, name="booking_confirmation", language="en",
                   status=TemplateStatus.APPROVED, components=[{"type": "BODY", "text": "Hi {{1}}, your stay is confirmed."}])
    db.add(t); db.commit()
    return t


def _route_send_message(db, tenant_id):
    conv = _conversation(db, tenant_id)
    return {"url": f"/api/v1/conversations/{conv.id}/messages", "json": {"body": "Hello guest"}, "ok": 201,
            "untouched": lambda: db.query(Message).filter_by(conversation_id=conv.id).count() == 0}


def _route_send_template(db, tenant_id):
    conv = _conversation(db, tenant_id)
    tmpl = _template(db, tenant_id)
    return {"url": f"/api/v1/conversations/{conv.id}/send-template", "json": {"template_id": tmpl.id, "variables": ["Priya"]},
            "ok": 201, "untouched": lambda: db.query(Message).filter_by(conversation_id=conv.id).count() == 0}


def _route_retry(db, tenant_id):
    conv = _conversation(db, tenant_id)
    msg = _message(db, tenant_id, conv.id, is_ai_generated=False, delivery_state=MessageDeliveryState.FAILED, delivery_error="x")

    def untouched():
        db.expire_all()
        return db.get(Message, msg.id).delivery_state == MessageDeliveryState.FAILED
    return {"url": f"/api/v1/conversations/{conv.id}/messages/{msg.id}/retry", "json": None, "ok": 200, "untouched": untouched}


def _route_approve(db, tenant_id):
    conv = _conversation(db, tenant_id)
    msg = _message(db, tenant_id, conv.id, is_ai_generated=True, was_approved=None)

    def untouched():
        db.expire_all()
        return db.get(Message, msg.id).was_approved is None
    return {"url": f"/api/v1/conversations/{conv.id}/messages/{msg.id}/approve", "json": {}, "ok": 200, "untouched": untouched}


ROUTES = pytest.mark.parametrize("route", [_route_send_message, _route_send_template, _route_retry, _route_approve],
                                 ids=["send_message", "send_template", "retry", "approve_draft"])


def _post(client, route, user, headers=None):
    return client.post(route["url"], json=route["json"], headers=headers or _headers(user))


@ROUTES
@pytest.mark.parametrize("role", SENDERS, ids=lambda r: r.value)
def test_roles_with_the_capability_can_send(client, db, route, role):
    tenant = _tenant(db)
    spec = route(db, tenant.id)
    with _Delivery() as delivery:
        resp = _post(client, spec, _user(db, tenant.id, role))
    assert resp.status_code == spec["ok"], resp.text
    assert delivery.fired == 1
    assert not spec["untouched"]()


@ROUTES
@pytest.mark.parametrize("role", NON_SENDERS, ids=lambda r: r.value)
def test_other_roles_are_refused_and_nothing_happens(client, db, route, role):
    tenant = _tenant(db)
    spec = route(db, tenant.id)
    with _Delivery() as delivery:
        resp = _post(client, spec, _user(db, tenant.id, role))
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "Insufficient permissions"
    assert delivery.fired == 0
    assert spec["untouched"]()


@ROUTES
def test_the_grant_is_the_tenants_to_take_away_even_from_foh(client, db, route):
    tenant = _tenant(db)
    _set_cell(db, tenant.id, *CELL, False)
    spec = route(db, tenant.id)
    with _Delivery() as delivery:
        resp = _post(client, spec, _user(db, tenant.id, UserRole.FOH))
    assert resp.status_code == 403, resp.text
    assert delivery.fired == 0 and spec["untouched"]()


@ROUTES
def test_a_tenant_without_a_capability_matrix_fails_closed(client, db, route):
    tenant = _tenant(db, provisioned=False)
    spec = route(db, tenant.id)
    with _Delivery() as delivery:
        resp = _post(client, spec, _user(db, tenant.id, UserRole.OWNER))
    assert resp.status_code == 403, resp.text
    assert delivery.fired == 0 and spec["untouched"]()


@ROUTES
def test_unauthenticated_requests_are_rejected(client, db, route):
    tenant = _tenant(db)
    spec = route(db, tenant.id)
    with _Delivery() as delivery:
        resp = client.post(spec["url"], json=spec["json"])
    assert resp.status_code in (401, 403)
    assert delivery.fired == 0 and spec["untouched"]()


@ROUTES
def test_another_tenants_conversation_cannot_be_used_and_is_not_revealed(client, db, route):
    mine, theirs = _tenant(db), _tenant(db)
    spec = route(db, theirs.id)
    with _Delivery() as delivery:
        allowed = _post(client, spec, _user(db, mine.id, UserRole.FOH))
        denied = _post(client, spec, _user(db, mine.id, UserRole.READ_ONLY))
    assert allowed.status_code == 404, allowed.text      # a sender still cannot reach another tenant's conversation
    assert denied.status_code == 403, denied.text        # and is refused before anything is looked up
    assert delivery.fired == 0 and spec["untouched"]()


def test_a_denied_role_gets_403_not_404_for_a_conversation_that_does_not_exist(client, db):
    tenant = _tenant(db)
    with _Delivery() as delivery:
        resp = client.post(f"/api/v1/conversations/{uuid.uuid4()}/messages", json={"body": "hi"},
                           headers=_headers(_user(db, tenant.id, UserRole.READ_ONLY)))
    assert resp.status_code == 403 and delivery.fired == 0


def test_foh_sends_are_idempotent_and_recorded_in_message_history(client, db):
    tenant = _tenant(db)
    foh = _user(db, tenant.id, UserRole.FOH)
    conv = _conversation(db, tenant.id)
    headers = _headers(foh, {"Idempotency-Key": str(uuid.uuid4())})
    with _Delivery() as delivery:
        first = client.post(f"/api/v1/conversations/{conv.id}/messages", json={"body": "Welcome!"}, headers=headers)
        second = client.post(f"/api/v1/conversations/{conv.id}/messages", json={"body": "Welcome!"}, headers=headers)
    # A replay returns the original message (the endpoint keeps status 201); what matters is that nothing new is created.
    assert first.status_code == 201 and second.status_code in (200, 201)
    assert first.json()["id"] == second.json()["id"]
    rows = db.query(Message).filter_by(conversation_id=conv.id).all()
    assert len(rows) == 1 and rows[0].body == "Welcome!" and rows[0].sender_id == foh.id
    assert delivery.fired == 1


def test_a_denied_send_leaves_no_audit_trail_changes_and_no_message(client, db):
    tenant = _tenant(db)
    conv = _conversation(db, tenant.id)
    audit_before = db.query(AuditEvent).filter_by(tenant_id=tenant.id).count()
    with _Delivery() as delivery:
        resp = client.post(f"/api/v1/conversations/{conv.id}/messages", json={"body": "hi"},
                           headers=_headers(_user(db, tenant.id, UserRole.MARKETING)))
    assert resp.status_code == 403 and delivery.fired == 0
    assert db.query(Message).filter_by(conversation_id=conv.id).count() == 0
    assert db.query(AuditEvent).filter_by(tenant_id=tenant.id).count() == audit_before
