"""Lead assignment rules (services/lead_assignment_service.py).

Leads auto-created from chats and calls used to sit unassigned forever; these
pin each method and rule the owner can switch on, plus the invariants: only
available agents on this team get leads, and the guest's conversations follow
the lead's owner.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.call import Call, CallDirection
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import inquiry_service
from app.services import lead_assignment_service as svc

NOW = datetime.now(timezone.utc)


def _tenant(db, **cfg):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"la-{uuid.uuid4().hex[:6]}", plan="growth",
               lead_assignment_config=cfg or None)
    db.add(t); db.flush(); return t


def _agent(db, tid, email, role=UserRole.CONCIERGE, available=True):
    u = User(id=str(uuid.uuid4()), tenant_id=tid, name=email.split("@")[0].title(), email=email,
             role=role, is_active=True, is_available_for_assignment=available)
    db.add(u); db.flush(); return u


def _guest(db, tid):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Guest", phone=f"+9198{uuid.uuid4().int % 10**8:08d}")
    db.add(g); db.flush(); return g


def _chat_lead(db, tid, guest=None):
    g = guest or _guest(db, tid)
    return inquiry_service.get_or_create_from_chat(db, tid, g.id, source="meta_ig", message_text="hi, rates?")


# ── Methods ───────────────────────────────────────────────────────────────────

def test_manual_mode_leaves_new_leads_unassigned_until_someone_acts(db):
    t = _tenant(db)  # no config -> manual
    a = _agent(db, t.id, "a@t.com")
    inq = _chat_lead(db, t.id)
    assert inq.assigned_to is None
    svc.claim_on_first_touch(db, t.id, inq.guest_id, a.id)
    assert inq.assigned_to == a.id and inq.assignment_method == "first_touch"


def test_round_robin_rotates_through_available_agents(db):
    t = _tenant(db, mode="round_robin")
    a, b = _agent(db, t.id, "a@t.com"), _agent(db, t.id, "b@t.com")
    owners = [_chat_lead(db, t.id).assigned_to for _ in range(4)]
    assert owners == [a.id, b.id, a.id, b.id]


def test_unavailable_and_non_sales_roles_never_get_leads(db):
    t = _tenant(db, mode="round_robin")
    a = _agent(db, t.id, "a@t.com")
    _agent(db, t.id, "off@t.com", available=False)
    _agent(db, t.id, "mkt@t.com", role=UserRole.MARKETING)
    owners = {_chat_lead(db, t.id).assigned_to for _ in range(3)}
    assert owners == {a.id}


def test_balanced_picks_the_agent_with_fewest_uncontacted_leads(db):
    t = _tenant(db)  # manual while we pre-load a's queue
    a, b = _agent(db, t.id, "a@t.com"), _agent(db, t.id, "b@t.com")
    for _ in range(2):
        svc._set_owner(db, _chat_lead(db, t.id), a.id, "manual", notify=False)
    t.lead_assignment_config = {"mode": "balanced"}; db.flush()
    assert _chat_lead(db, t.id).assigned_to == b.id


def test_other_tenants_agents_are_never_picked(db):
    t, other = _tenant(db, mode="round_robin"), _tenant(db)
    _agent(db, other.id, "x@o.com")
    mine = _agent(db, t.id, "a@t.com")
    assert _chat_lead(db, t.id).assigned_to == mine.id


# ── Rules ─────────────────────────────────────────────────────────────────────

def test_returning_guest_goes_back_to_their_previous_agent(db):
    t = _tenant(db, mode="round_robin", returning_guest_same_agent=True)
    a, b = _agent(db, t.id, "a@t.com"), _agent(db, t.id, "b@t.com")
    g = _guest(db, t.id)
    old = Inquiry(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, stage=InquiryStage.LOST,
                  assigned_to=b.id, created_at=NOW - timedelta(days=40))
    db.add(old); db.flush()
    inq = _chat_lead(db, t.id, guest=g)
    assert inq.assigned_to == b.id and inq.assignment_method == "returning_guest"


def test_outside_working_hours_waits_then_assigns_at_opening(db, monkeypatch):
    t = _tenant(db, mode="round_robin", working_hours_only=True, hours_start="09:00", hours_end="18:00")
    a = _agent(db, t.id, "a@t.com")
    night = datetime(2026, 9, 22, 17, 0, tzinfo=timezone.utc)  # 22:30 IST
    monkeypatch.setattr(svc, "_now", lambda: night)
    inq = _chat_lead(db, t.id)
    assert inq.assigned_to is None
    morning = datetime(2026, 9, 23, 4, 0, tzinfo=timezone.utc)  # 09:30 IST
    monkeypatch.setattr(svc, "_now", lambda: morning)
    inq.created_at = morning - timedelta(hours=11); db.flush()
    svc.run_tick(db, t, now=morning)
    assert inq.assigned_to == a.id


def test_uncontacted_lead_is_passed_on_and_contacted_one_stays(db):
    t = _tenant(db, mode="round_robin", reassign_if_not_contacted=True, reassign_after_minutes=30)
    a, b = _agent(db, t.id, "a@t.com"), _agent(db, t.id, "b@t.com")
    stale = _chat_lead(db, t.id)
    handled = _chat_lead(db, t.id)
    assert stale.assigned_to == a.id and handled.assigned_to == b.id
    for inq in (stale, handled):
        inq.assigned_at = NOW - timedelta(minutes=45)
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=handled.guest_id,
                        channel=ChannelType.INSTAGRAM, is_open=True)
    db.add(conv); db.flush()
    db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=conv.id, direction="outbound",
                   channel=ChannelType.INSTAGRAM, body="Hi!", sender_id=b.id, is_ai_generated=False,
                   created_at=NOW - timedelta(minutes=20)))
    db.flush()
    res = svc.run_tick(db, t, now=NOW)
    assert res["reassigned"] == 1
    assert stale.assigned_to == b.id and stale.assignment_method == "reassigned" and stale.assignment_attempts == 1
    assert handled.assigned_to == b.id and handled.assignment_method == "round_robin"


def test_ai_only_replies_do_not_count_as_contact(db):
    t = _tenant(db, mode="round_robin", reassign_if_not_contacted=True, reassign_after_minutes=30)
    a, b = _agent(db, t.id, "a@t.com"), _agent(db, t.id, "b@t.com")
    inq = _chat_lead(db, t.id)
    inq.assigned_at = NOW - timedelta(hours=1)
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=inq.guest_id,
                        channel=ChannelType.INSTAGRAM, is_open=True)
    db.add(conv); db.flush()
    db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=conv.id, direction="outbound",
                   channel=ChannelType.INSTAGRAM, body="bot reply", is_ai_generated=True,
                   created_at=NOW - timedelta(minutes=50)))
    db.flush()
    svc.run_tick(db, t, now=NOW)
    assert inq.assigned_to == b.id


def _call(db, tid, guest_id, agent_id, direction=CallDirection.INBOUND, seconds=120):
    c = Call(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest_id, ivr_provider="vobiz",
             ivr_call_id=f"c-{uuid.uuid4().hex[:8]}", direction=direction, from_number="+911", to_number="+912",
             duration_seconds=seconds, agent_id=agent_id, created_at=NOW)
    db.add(c); db.flush(); return c


def test_answered_call_gives_an_unowned_lead_to_the_answering_agent(db):
    t = _tenant(db)
    a = _agent(db, t.id, "a@t.com")
    g = _guest(db, t.id)
    inq = inquiry_service.get_or_create_from_call(db, t.id, g.id, direction="inbound", answered=True)
    svc.on_call_logged(db, inq, _call(db, t.id, g.id, a.id))
    assert inq.assigned_to == a.id


def test_call_answerer_takes_over_a_rule_assigned_untouched_lead(db):
    t = _tenant(db, mode="round_robin", call_answerer_owns=True)
    a, b = _agent(db, t.id, "a@t.com"), _agent(db, t.id, "b@t.com")
    inq = _chat_lead(db, t.id)
    assert inq.assigned_to == a.id
    svc.on_call_logged(db, inq, _call(db, t.id, inq.guest_id, b.id))
    assert inq.assigned_to == b.id and inq.assignment_method == "call_answered"


def test_owner_change_moves_the_guests_conversations(db):
    t = _tenant(db, mode="round_robin")
    a = _agent(db, t.id, "a@t.com")
    g = _guest(db, t.id)
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id,
                        channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv); db.flush()
    _chat_lead(db, t.id, guest=g)
    db.refresh(conv)
    assert conv.assigned_to == a.id


def test_invalid_saved_config_falls_back_to_manual(db):
    t = _tenant(db, mode="teleport")
    _agent(db, t.id, "a@t.com")
    assert _chat_lead(db, t.id).assigned_to is None


# ── Settings API ──────────────────────────────────────────────────────────────

def test_owner_can_read_and_update_settings(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    agent = _agent(db, tid, f"ag-{uuid.uuid4().hex[:5]}@t.com"); db.commit()
    h = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    r = client.get("/api/v1/tenants/me/lead-assignment", headers=h)
    assert r.status_code == 200 and r.json()["mode"] == "manual"
    r = client.patch("/api/v1/tenants/me/lead-assignment", headers=h, json={
        "config": {"mode": "balanced", "reassign_if_not_contacted": True, "reassign_after_minutes": 20},
        "agents": {agent.id: False},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "balanced" and body["reassign_after_minutes"] == 20
    assert next(x for x in body["agents"] if x["id"] == agent.id)["takes_leads"] is False


def test_agent_role_cannot_change_settings(client, db, tenant_and_user):
    from app.core.security import create_access_token
    ag = _agent(db, tenant_and_user["tenant"].id, f"c-{uuid.uuid4().hex[:5]}@t.com"); db.commit()
    tok = create_access_token({"sub": ag.id, "tenant_id": ag.tenant_id, "role": ag.role.value})
    r = client.patch("/api/v1/tenants/me/lead-assignment", headers={"Authorization": f"Bearer {tok}"},
                     json={"config": {"mode": "round_robin"}})
    assert r.status_code == 403


def test_cannot_toggle_someone_from_another_team(client, db, tenant_and_user):
    other = _tenant(db)
    outsider = _agent(db, other.id, f"o-{uuid.uuid4().hex[:5]}@o.com"); db.commit()
    h = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    r = client.patch("/api/v1/tenants/me/lead-assignment", headers=h, json={"agents": {outsider.id: False}})
    assert r.status_code == 422
    db.refresh(outsider)
    assert outsider.is_available_for_assignment is True


def test_bad_hours_are_rejected(client, tenant_and_user):
    h = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    r = client.patch("/api/v1/tenants/me/lead-assignment", headers=h,
                     json={"config": {"mode": "round_robin", "working_hours_only": True, "hours_start": "25:00"}})
    assert r.status_code == 422
