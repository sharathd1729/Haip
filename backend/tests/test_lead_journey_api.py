"""Lead journey (milestones per enquiry) and the Workflows API: refresh from source rows, views, outcome, the endpoints'
roles, lead visibility and tenant isolation."""
import uuid
from datetime import datetime, timedelta, timezone

from app.core.security import create_access_token, get_password_hash
from app.models.audit_event import AuditEvent
from app.models.call import Call, CallDirection
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.inquiry_360 import InquiryQuote
from app.models.lead_workflow import LeadJourney, LeadView
from app.models.pipeline_stage import PipelineStage
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import lead_journey_tracker as journey

API = "/api/v1"


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _user(db, tenant_id, role):
    u = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name=f"{role.value} person", email=f"{uuid.uuid4().hex[:8]}@t.com",
             hashed_password=get_password_hash("pw-123456789"), role=role, is_active=True)
    db.add(u)
    db.commit()
    return u, create_access_token({"sub": u.id, "tenant_id": tenant_id, "role": role.value})


def _lead(db, tenant_id, created=None, owner=None):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Meera", phone="+919876500011")
    db.add(guest)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, assigned_to=owner,
                  created_at=created or datetime.now(timezone.utc) - timedelta(hours=3))
    db.add(inq)
    db.commit()
    return guest, inq


# ── Journey service ─────────────────────────────────────────────────────────

def test_refresh_fills_milestones_from_source_rows(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    guest, inq = _lead(db, tid)
    now = datetime.now(timezone.utc)
    db.add(Call(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, ivr_provider="vobiz", ivr_call_id="j1",
                direction=CallDirection.OUTBOUND, from_number="+91", to_number=guest.phone, duration_seconds=0,
                ivr_dial_status="no-answer", created_at=now - timedelta(hours=2)))
    db.add(Call(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, ivr_provider="vobiz", ivr_call_id="j2",
                direction=CallDirection.OUTBOUND, from_number="+91", to_number=guest.phone, duration_seconds=120,
                ivr_dial_status="completed", created_at=now - timedelta(hours=1)))
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, channel=ChannelType.INSTAGRAM, is_open=True)
    db.add(conv)
    db.flush()
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.OUTBOUND,
                   channel=ChannelType.INSTAGRAM, body="Hello!", created_at=now - timedelta(minutes=150)))
    db.add(InquiryQuote(tenant_id=tid, inquiry_id=inq.id, amount=45000, shared_via="copied", shared_at=now - timedelta(minutes=30)))
    db.commit()

    journey.refresh(db, tid, [inq])
    db.commit()
    row = db.query(LeadJourney).filter_by(tenant_id=tid, inquiry_id=inq.id).one()
    assert row.received_at is not None
    assert row.first_call_attempt_at is not None and row.first_connected_at is not None
    assert row.first_human_contact_channel == "instagram"         # the Instagram reply came before the answered call
    assert row.proposal_mode == "copied" and row.proposal_channel == "copied"
    first = row.first_human_contact_at
    journey.refresh(db, tid, [inq])                              # write-once: a second pass changes nothing
    db.commit()
    db.refresh(row)
    assert row.first_human_contact_at == first


def test_view_outcome_and_isolation(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    owner = tenant_and_user["user"]
    guest, inq = _lead(db, tid)
    journey.record_view(db, tid, inq.id, owner.id)
    journey.record_view(db, tid, inq.id, owner.id)
    db.commit()
    view = db.query(LeadView).filter_by(tenant_id=tid, inquiry_id=inq.id).one()
    assert view.views == 2
    assert db.query(LeadJourney).filter_by(inquiry_id=inq.id).one().first_viewed_by == owner.id
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    assert journey.record_view(db, other.id, inq.id, owner.id) is None     # another workspace's lead: nothing written

    lost = PipelineStage(tenant_id=tid, key="lost", label="Lost", category="valid", is_closed_lost=True, order=5)
    db.add(lost)
    db.flush()
    inq.stage_id, inq.lost_reason = lost.id, "budget_mismatch"
    journey.on_stage_changed(db, inq)
    db.commit()
    row = db.query(LeadJourney).filter_by(inquiry_id=inq.id).one()
    assert row.outcome == "lost" and row.lost_reason == "budget_mismatch" and row.outcome_at is not None


# ── Endpoints ───────────────────────────────────────────────────────────────

def test_catalog_settings_and_roles(client, db, tenant_and_user, capabilities_seeded):
    tid = _tid(tenant_and_user)
    owner_h = _h(tenant_and_user["access_token"])
    r = client.get(f"{API}/workflows/catalog", headers=owner_h)
    assert r.status_code == 200
    body = r.json()
    p1 = next(p for p in body["playbooks"] if p["key"] == "missed_inbound_call")
    assert p1["settings"]["enabled"] is False and p1["template"]["status"] is None

    r = client.put(f"{API}/workflows/settings", headers=owner_h, json={"playbooks": {"missed_inbound_call": {"enabled": True}}})
    assert r.status_code == 200
    assert next(p for p in r.json()["playbooks"] if p["key"] == "missed_inbound_call")["settings"]["enabled"] is True
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="workflows.settings_changed").count() == 1
    r = client.put(f"{API}/workflows/settings", headers=owner_h, json={"playbooks": {"proposal_followup": {"enabled": True}}})
    assert r.status_code == 422

    r = client.post(f"{API}/workflows/templates/lead-pack", headers=owner_h)
    assert r.status_code == 200 and set(r.json()["created"]) == {
        "haip_missed_call_v1", "haip_tried_calling_v1", "haip_staff_lead_alert_v1", "haip_staff_escalation_v1", "haip_staff_digest_v1"}

    _, agent_token = _user(db, tid, UserRole.CONCIERGE)
    assert client.get(f"{API}/workflows/catalog", headers=_h(agent_token)).status_code == 403
    assert client.put(f"{API}/workflows/settings", headers=_h(agent_token), json={"enabled": False}).status_code == 403

    r = client.patch(f"{API}/tenants/me", headers=owner_h, json={"brand_config": {"lead_playbooks": {"enabled": False}}})
    assert r.status_code == 422


def test_journey_viewed_pause_visibility_and_cross_tenant(client, db, tenant_and_user, capabilities_seeded):
    tid = _tid(tenant_and_user)
    owner_h = _h(tenant_and_user["access_token"])
    guest, inq = _lead(db, tid)
    r = client.post(f"{API}/leads/{inq.id}/viewed", headers=owner_h)
    assert r.status_code == 200 and r.json()["views"] == 1
    r = client.get(f"{API}/leads/{inq.id}/journey", headers=owner_h)
    assert r.status_code == 200
    steps = {s["key"]: s for s in r.json()["steps"]}
    assert steps["received"]["at"] and steps["viewed"]["at"]

    r = client.post(f"{API}/leads/{inq.id}/playbooks/pause", headers=owner_h, json={"paused": True})
    assert r.status_code == 200 and r.json()["paused"] is True
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="workflows.lead_paused").count() == 1

    # A concierge cannot open a teammate's lead (404, like another workspace's).
    _, agent_token = _user(db, tid, UserRole.CONCIERGE)
    teammate, _ = _user(db, tid, UserRole.CONCIERGE)
    _, theirs = _lead(db, tid, owner=teammate.id)
    assert client.get(f"{API}/leads/{theirs.id}/journey", headers=_h(agent_token)).status_code == 404

    # Another workspace's owner gets 404 on this lead.
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    from tests.conftest import seed_capabilities
    seed_capabilities(db, other.id)
    _, other_token = _user(db, other.id, UserRole.OWNER)
    assert client.get(f"{API}/leads/{inq.id}/journey", headers=_h(other_token)).status_code == 404
    assert client.post(f"{API}/leads/{inq.id}/viewed", headers=_h(other_token)).status_code == 404
    assert client.post(f"{API}/leads/{inq.id}/playbooks/pause", headers=_h(other_token), json={"paused": False}).status_code == 404
    r = client.get(f"{API}/workflows/activity", headers=_h(other_token))
    assert r.status_code == 200 and r.json()["items"] == []
