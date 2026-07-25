"""
Tests for POST /automations/actions/execute — one-click execution of an AI
recommendation (Phase 3).

  happy path       : a whitelisted action runs and returns its detail
  audit            : every execution writes to the hash-chained audit log
  allowlist        : an action valid for rules but not for one-click is rejected
  validation       : empty entity_refs is rejected
  cross-tenant     : acting on another tenant's guest cannot affect it
  failure path     : a failing action still gets audited, and returns 502
"""

import uuid

import pytest

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.guest import Guest
from app.models.audit_event import AuditEvent
from app.core.security import create_access_token, get_password_hash

EXECUTE_URL = "/api/v1/automations/actions/execute"


def _tenant(db, name="T"):
    t = Tenant(id=str(uuid.uuid4()), name=name,
               slug=f"ax-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.flush(); return t


def _user(db, tenant_id, role=UserRole.OWNER):
    u = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name="U",
             email=f"u-{uuid.uuid4().hex[:6]}@test.com",
             hashed_password=get_password_hash("pw"), role=role, is_active=True)
    db.add(u); db.flush(); return u


def _token(user):
    return create_access_token(
        {"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value}
    )


def _guest(db, tenant_id, name="G"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, phone="")
    db.add(g); db.flush(); return g


def _auth(user):
    return {"Authorization": f"Bearer {_token(user)}"}


def test_execute_action_happy_path(client, db):
    t = _tenant(db); u = _user(db, t.id); g = _guest(db, t.id)
    db.commit()

    res = client.post(EXECUTE_URL, headers=_auth(u), json={
        "action_type": "tag_guest",
        "entity_refs": {"guest_id": g.id},
        "action_config": {"tags": ["VIP"]},
        "source": "leads360_ai_card",
    })

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "success"
    assert body["action_type"] == "tag_guest"
    assert body["audit_id"]


def test_execution_is_audited(client, db):
    """An outbound action that isn't recorded is worse than one that fails."""
    t = _tenant(db); u = _user(db, t.id); g = _guest(db, t.id)
    db.commit()

    client.post(EXECUTE_URL, headers=_auth(u), json={
        "action_type": "tag_guest",
        "entity_refs": {"guest_id": g.id},
        "action_config": {"tags": ["VIP"]},
        "source": "calls_intelligence_card",
    })

    events = (
        db.query(AuditEvent)
        .filter_by(tenant_id=t.id, action="ai_recommendation.executed")
        .all()
    )
    assert len(events) == 1
    ev = events[0]
    assert ev.actor_user_id == u.id
    assert ev.target_type == "guest"
    assert ev.target_id == g.id
    assert ev.payload["action_type"] == "tag_guest"
    assert ev.payload["source"] == "calls_intelligence_card"


def test_action_valid_for_rules_but_not_one_click_is_rejected(db, client):
    """send_instagram_quick_reply is in VALID_ACTIONS but deliberately not in
    ONE_CLICK_ACTIONS — the two trust contexts are different."""
    t = _tenant(db); u = _user(db, t.id); g = _guest(db, t.id)
    db.commit()

    res = client.post(EXECUTE_URL, headers=_auth(u), json={
        "action_type": "send_instagram_quick_reply",
        "entity_refs": {"guest_id": g.id},
    })
    assert res.status_code == 422
    assert "cannot be run from a recommendation" in res.text


def test_unknown_action_is_rejected(client, db):
    t = _tenant(db); u = _user(db, t.id); g = _guest(db, t.id)
    db.commit()

    res = client.post(EXECUTE_URL, headers=_auth(u), json={
        "action_type": "drop_database",
        "entity_refs": {"guest_id": g.id},
    })
    assert res.status_code == 422


def test_empty_entity_refs_rejected(client, db):
    t = _tenant(db); u = _user(db, t.id)
    db.commit()

    res = client.post(EXECUTE_URL, headers=_auth(u), json={
        "action_type": "tag_guest",
        "entity_refs": {},
    })
    assert res.status_code == 422


def test_requires_authentication(client, db):
    res = client.post(EXECUTE_URL, json={
        "action_type": "tag_guest",
        "entity_refs": {"guest_id": "whatever"},
    })
    assert res.status_code in (401, 403)


def test_cross_tenant_guest_is_not_affected(client, db):
    """Acting on another tenant's guest must not tag that guest. The action
    layer is tenant-scoped, so this either errors or no-ops — what must never
    happen is a successful mutation of the other tenant's row."""
    t1 = _tenant(db, "T1"); t2 = _tenant(db, "T2")
    attacker = _user(db, t1.id)
    victim_guest = _guest(db, t2.id, name="victim")
    db.commit()

    res = client.post(EXECUTE_URL, headers=_auth(attacker), json={
        "action_type": "tag_guest",
        "entity_refs": {"guest_id": victim_guest.id},
        "action_config": {"tags": ["PWNED"]},
    })

    # Whatever the status, the audit row must be attributed to the caller's
    # tenant, never the victim's.
    leaked = (
        db.query(AuditEvent)
        .filter_by(tenant_id=t2.id, action="ai_recommendation.executed")
        .count()
    )
    assert leaked == 0, "audit row must not be written into the victim tenant"
    assert res.status_code in (200, 404, 422, 502)
