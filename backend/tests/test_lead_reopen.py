"""Moving a lead out of Lost: by hand (PATCH /inquiries, MCP: owner/manager + reason, 403 otherwise) and automatically
(lead_reopen: the guest writes / calls again, or our contact reaches a lead the SYSTEM closed). Sold always stays Sold."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.audit_event import AuditEvent
from app.models.call import Call, CallDirection
from app.models.conversation import ChannelType, Conversation
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage
from app.models.inquiry_360 import InquiryStageLog
from app.models.pipeline_stage import PipelineStage
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import inquiry_service, lead_reopen
from app.services.inquiry_service import InvalidStageTransition, ReopenNotAllowed
from app.services.pipeline_stage_service import seed_default_pipeline_stages


def _stages(db, tid):
    if not db.query(PipelineStage).filter_by(tenant_id=tid).count():
        seed_default_pipeline_stages(db, tid)
        db.commit()
    return {s.key: s for s in db.query(PipelineStage).filter_by(tenant_id=tid)}


def _user(db, tid, role):
    u = User(id=str(uuid.uuid4()), tenant_id=tid, name=role.value.title(), email=f"{uuid.uuid4().hex[:8]}@t.com",
             hashed_password=get_password_hash("x" * 12), role=role, is_active=True)
    db.add(u)
    db.commit()
    return u


def _auth(u):
    return {"Authorization": "Bearer " + create_access_token({"sub": u.id, "tenant_id": u.tenant_id, "role": u.role.value})}


def _lost_lead(db, tid, by="system", stage_key="lost", phone=None):
    st = _stages(db, tid)
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Shwetha M", phone=phone or f"+9198{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    db.flush()
    stage = st[stage_key]
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, stage_id=stage.id,
                  stage=InquiryStage.BOOKED if stage.is_closed_won else InquiryStage.LOST,
                  created_at=datetime.now(timezone.utc) - timedelta(days=20))
    db.add(inq)
    db.add(InquiryStageLog(tenant_id=tid, inquiry_id=inq.id, from_stage="active", to_stage=stage.key, changed_by=by,
                           changed_at=datetime.now(timezone.utc) - timedelta(days=3), reason="closed"))
    db.commit()
    return g, inq, st


def _tid(tu):
    return tu["tenant"].id


# ── Manual: PATCH /inquiries/{id} ───────────────────────────────────────────────────────────────────────────────────
def test_owner_reopens_a_lost_lead_with_a_reason(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _, inq, st = _lost_lead(db, tid, by=tenant_and_user["user"].id)
    inq.lost_reason = None
    db.commit()
    r = client.patch(f"/api/v1/inquiries/{inq.id}", json={"stage_id": st["active"].id, "reason": "Marked lost by mistake"},
                     headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"})
    assert r.status_code == 200, r.text
    db.refresh(inq)
    assert inq.stage_id == st["active"].id and inq.stage != InquiryStage.LOST
    ev = db.query(AuditEvent).filter_by(tenant_id=tid, action="inquiry.stage_changed", target_id=inq.id).one()
    assert ev.payload["from_stage"] == "lost" and ev.payload["reason"] == "Marked lost by mistake"


def test_reopen_needs_a_reason(client, db, tenant_and_user):
    _, inq, st = _lost_lead(db, _tid(tenant_and_user), by=tenant_and_user["user"].id)
    r = client.patch(f"/api/v1/inquiries/{inq.id}", json={"stage_id": st["active"].id},
                     headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"})
    assert r.status_code == 422 and "reason is required" in r.json()["detail"]


def test_other_roles_get_a_clear_403(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _, inq, st = _lost_lead(db, tid, by=tenant_and_user["user"].id)
    agent = _user(db, tid, UserRole.RESERVATIONS)
    r = client.patch(f"/api/v1/inquiries/{inq.id}", json={"stage_id": st["active"].id, "reason": "guest is back"},
                     headers=_auth(agent))
    assert r.status_code == 403
    assert r.json()["detail"] == "Only an owner or manager can reopen a lost lead."
    db.refresh(inq)
    assert inq.stage_id == st["lost"].id


def test_another_workspace_cannot_reopen(client, db, tenant_and_user):
    _, inq, st = _lost_lead(db, _tid(tenant_and_user))
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    boss = _user(db, other.id, UserRole.OWNER)
    r = client.patch(f"/api/v1/inquiries/{inq.id}", json={"stage_id": st["active"].id, "reason": "x"}, headers=_auth(boss))
    assert r.status_code == 404
    db.refresh(inq)
    assert inq.stage_id == st["lost"].id


def test_sold_stays_sold(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _, inq, st = _lost_lead(db, tid, stage_key="sold")
    with pytest.raises(InvalidStageTransition, match="stays Sold"):
        inquiry_service.update_stage_by_id(db, tenant_id=tid, inquiry_id=inq.id, new_stage_id=st["active"].id,
                                           actor_user_id=tenant_and_user["user"].id, actor_role="owner", reason="x")


def test_mcp_move_lead_stage_reopens_for_a_manager_and_refuses_others(db, tenant_and_user):
    from app.mcp.tools import ToolError, _move_lead_stage
    tid = _tid(tenant_and_user)
    _, inq, st = _lost_lead(db, tid, by=tenant_and_user["user"].id)
    with pytest.raises(ToolError, match="Only an owner or manager"):
        _move_lead_stage(db, _user(db, tid, UserRole.CONCIERGE), tid, {"inquiry_id": inq.id, "new_stage_id": st["active"].id,
                                                                         "reason": "back"})
    out = _move_lead_stage(db, _user(db, tid, UserRole.MANAGER), tid,
                           {"inquiry_id": inq.id, "new_stage_id": st["active"].id, "reason": "back"})
    assert out["stage_id"] == st["active"].id


def test_reopen_not_allowed_is_the_403_kind():
    assert issubclass(ReopenNotAllowed, InvalidStageTransition)


# ── Automatic: lead_reopen ──────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("closed_by", ["system", "person"])
def test_guest_writing_again_reopens_and_the_chat_lookup_reuses_the_lead(db, tenant_and_user, closed_by):
    tid = _tid(tenant_and_user)
    by = "system" if closed_by == "system" else tenant_and_user["user"].id
    g, inq, st = _lost_lead(db, tid, by=by)
    assert lead_reopen.on_contact(db, tid, g.id, trigger="whatsapp_message", by_guest=True) is not None
    db.commit()
    db.refresh(inq)
    assert inq.stage_id == st["active"].id
    again = inquiry_service.get_or_create_from_chat(db, tid, g.id, source="wa_direct", message_text="Hi, still available?")
    assert again.id == inq.id                                       # no duplicate lead
    assert db.query(Inquiry).filter_by(tenant_id=tid, guest_id=g.id).count() == 1
    ev = db.query(AuditEvent).filter_by(tenant_id=tid, action="lead.auto_reopened", target_id=inq.id).one()
    assert ev.payload["trigger"] == "whatsapp_message" and ev.payload["closed_by"] == closed_by


def test_our_outreach_reopens_only_a_lead_the_system_closed(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    g1, sys_lead, st = _lost_lead(db, tid, by="system")
    g2, person_lead, _ = _lost_lead(db, tid, by=tenant_and_user["user"].id)
    me = tenant_and_user["user"].id
    assert lead_reopen.on_contact(db, tid, g1.id, trigger="team_message", by_guest=False, actor_user_id=me)
    assert lead_reopen.on_contact(db, tid, g2.id, trigger="team_message", by_guest=False, actor_user_id=me) is None
    db.commit()
    db.refresh(sys_lead)
    db.refresh(person_lead)
    assert sys_lead.stage_id == st["active"].id and person_lead.stage_id == st["lost"].id


def test_sold_is_never_reopened_automatically(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    g, inq, st = _lost_lead(db, tid, by="system", stage_key="sold")
    assert lead_reopen.on_contact(db, tid, g.id, trigger="whatsapp_message", by_guest=True) is None
    db.refresh(inq)
    assert inq.stage_id == st["sold"].id


def test_an_open_lead_takes_the_activity_and_another_tenant_is_untouched(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    g, lost, st = _lost_lead(db, tid, by="system")
    newer = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, stage_id=st["active"].id, stage=InquiryStage.RESPONDING)
    db.add(newer)
    db.commit()
    assert lead_reopen.on_contact(db, tid, g.id, trigger="whatsapp_message", by_guest=True) is None
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    g2, lost2, _ = _lost_lead(db, tid, by="system")
    assert lead_reopen.on_contact(db, other.id, g2.id, trigger="whatsapp_message", by_guest=True) is None
    db.refresh(lost)
    db.refresh(lost2)
    assert lost.stage_id == st["lost"].id and lost2.stage_id == st["lost"].id


def _call(db, tid, g, inq, direction, answered):
    c = Call(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, inquiry_id=inq.id, ivr_provider="vobiz",
             ivr_call_id=f"c-{uuid.uuid4().hex[:8]}", from_number=g.phone, to_number="+912200000000",
             direction=CallDirection.INBOUND if direction == "inbound" else CallDirection.OUTBOUND,
             duration_seconds=90 if answered else 0, ivr_dial_status="completed" if answered else "no-answer")
    db.add(c)
    db.commit()
    return c


def test_calls_guest_calling_reopens_our_unanswered_call_does_not(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    g1, person_lead, st = _lost_lead(db, tid, by=tenant_and_user["user"].id)
    assert lead_reopen.on_call(db, _call(db, tid, g1, person_lead, "inbound", answered=False))      # the guest called us
    g2, sys_lead, _ = _lost_lead(db, tid, by="system")
    assert lead_reopen.on_call(db, _call(db, tid, g2, sys_lead, "outbound", answered=False)) is None
    assert lead_reopen.on_call(db, _call(db, tid, g2, sys_lead, "outbound", answered=True))
    g3, person2, _ = _lost_lead(db, tid, by=tenant_and_user["user"].id)
    assert lead_reopen.on_call(db, _call(db, tid, g3, person2, "outbound", answered=True)) is None   # our call, a person's Lost
    db.commit()
    assert [db.get(Inquiry, i.id).stage_id for i in (person_lead, sys_lead, person2)] == [st["active"].id, st["active"].id, st["lost"].id]


def test_outbound_call_to_a_person_marked_lost_lead_joins_it_without_a_new_lead(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    g, inq, _ = _lost_lead(db, tid, by=tenant_and_user["user"].id)
    got = inquiry_service.get_or_create_from_call(db, tid, g.id, direction="outbound", answered=True)
    assert got.id == inq.id and db.query(Inquiry).filter_by(tenant_id=tid, guest_id=g.id).count() == 1


def test_inbox_send_reopens_system_closed_but_not_person_closed(client, db, tenant_and_user):
    from tests.conftest import seed_capabilities
    tid = _tid(tenant_and_user)
    seed_capabilities(db, tid)
    hdr = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    out = {}
    for by in ("system", tenant_and_user["user"].id):
        g, inq, st = _lost_lead(db, tid, by=by)
        conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True,
                            inquiry_id=inq.id)
        db.add(conv)
        db.commit()
        with patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay"):
            r = client.post(f"/api/v1/conversations/{conv.id}/messages", json={"body": "Hi, are you still planning?"}, headers=hdr)
        assert r.status_code == 201, r.text
        db.refresh(inq)
        out[by == "system"] = inq.stage_id
    assert out[True] == st["active"].id and out[False] == st["lost"].id


def test_autopilot_does_not_close_a_reopened_lead_again_for_an_old_date(db, tenant_and_user):
    from app.services import lead_autopilot_rules as rules
    tid = _tid(tenant_and_user)
    g, inq, st = _lost_lead(db, tid, by="system")
    g.lead_identified_at = datetime.now(timezone.utc) - timedelta(days=20)
    inq.check_in = (datetime.now(timezone.utc) - timedelta(days=5)).date().isoformat()
    db.commit()
    lead_reopen.on_contact(db, tid, g.id, trigger="whatsapp_message", by_guest=True)
    db.commit()
    db.refresh(inq)
    from app.services.lead_autopilot_service import get_settings
    decision = rules.evaluate(db, tid, inq, rules.StageMap.load(db, tid), get_settings(db, tid))
    assert decision is None or decision.rule != "dates_passed"
