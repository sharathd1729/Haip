"""POST /leads/{id}/log-call: a call from an agent's own phone (lead_call_log). Pinned: a connected call is contact, closes
the guest's call-back reminders and returns the missed call (the lead page's next step stops saying "Call back"); an
unanswered one is only an attempt; it is audited; read_only is refused; another workspace's lead and a teammate's lead (for
a scoped role) are 404."""
import uuid
from datetime import datetime, timedelta, timezone

from app.models.audit_event import AuditEvent
from app.models.call import Call, CallDirection
from app.models.task import Task
from app.models.tenant import Tenant
from app.models.user import UserRole
from tests.conftest import seed_capabilities
from tests.test_lead_feed import _lead, _owner_headers, _user

NOW = datetime.now(timezone.utc)


def _missed(db, tid, g, inq, hours_ago=2):
    c = Call(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, inquiry_id=inq.id, ivr_provider="vobiz",
             ivr_call_id=uuid.uuid4().hex, direction=CallDirection.INBOUND, from_number=g.phone, to_number="+918000000000",
             duration_seconds=0, ivr_dial_status="no-answer", created_at=NOW - timedelta(hours=hours_ago))
    db.add(c)
    db.add(Task(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, inquiry_id=inq.id, title="Call back — missed call from Sharath",
                is_done=False, due_date=NOW - timedelta(hours=1)))
    db.commit()
    return c


def _post(client, inquiry_id, headers, **body):
    return client.post(f"/api/v1/leads/{inquiry_id}/log-call", headers=headers, json=body)


def test_a_connected_call_logged_by_hand_returns_the_missed_call(client, db, tenant_and_user):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    seed_capabilities(db, tenant.id)
    g, inq = _lead(db, tenant.id, owner.id)
    missed = _missed(db, tenant.id, g, inq)
    h = _owner_headers(tenant_and_user)
    assert client.get(f"/api/v1/leads/{inq.id}/feed", headers=h).json()["facts"]["missed_inbound_unreturned"] is True

    res = _post(client, inq.id, h, outcome="connected", duration_minutes=4, note="Wants the 2-night Coorg plan")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["callbacks_closed"] == 1 and body["missed_calls_returned"] == 1 and body["duration_seconds"] == 240

    call = db.query(Call).filter_by(id=body["call_id"]).one()
    assert call.ivr_provider == "manual" and call.direction == CallDirection.OUTBOUND and call.agent_id == owner.id
    assert call.guest_id == g.id and call.tenant_id == tenant.id
    db.refresh(missed)
    assert missed.callback_dismissed_at is not None and missed.recovered_by_call_id == call.id
    assert db.query(Task).filter_by(tenant_id=tenant.id, guest_id=g.id, is_done=False).count() == 0
    assert db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="call.logged_manually", target_id=call.id).count() == 1

    feed = client.get(f"/api/v1/leads/{inq.id}/feed", headers=h).json()
    assert feed["facts"]["missed_inbound_unreturned"] is False
    logged = [i for i in feed["items"] if i["kind"] == "call" and i["call_id"] == call.id][0]
    assert logged["manual"] is True and logged["answered"] is True and logged["text"] == "Wants the 2-night Coorg plan"


def test_an_unanswered_call_logged_by_hand_is_only_an_attempt(client, db, tenant_and_user):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    seed_capabilities(db, tenant.id)
    g, inq = _lead(db, tenant.id, owner.id)
    missed = _missed(db, tenant.id, g, inq)
    res = _post(client, inq.id, _owner_headers(tenant_and_user), outcome="voicemail")
    assert res.status_code == 201 and res.json()["callbacks_closed"] == 0
    db.refresh(missed)
    assert missed.callback_dismissed_at is None
    feed = client.get(f"/api/v1/leads/{inq.id}/feed", headers=_owner_headers(tenant_and_user)).json()
    assert feed["facts"]["unanswered_outbound_calls"] == 1


def test_read_only_cannot_log_a_call_and_a_bad_outcome_is_refused(client, db, tenant_and_user):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    seed_capabilities(db, tenant.id)
    g, inq = _lead(db, tenant.id, owner.id)
    _, ro = _user(db, tenant.id, UserRole.READ_ONLY)
    assert _post(client, inq.id, ro, outcome="connected").status_code == 403
    assert _post(client, inq.id, _owner_headers(tenant_and_user), outcome="maybe").status_code == 422
    assert db.query(Call).filter_by(tenant_id=tenant.id, ivr_provider="manual").count() == 0


def test_another_workspaces_lead_and_a_teammates_lead_are_not_found(client, db, tenant_and_user):
    tenant, owner = tenant_and_user["tenant"], tenant_and_user["user"]
    seed_capabilities(db, tenant.id)
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other); db.commit()
    seed_capabilities(db, other.id)
    og, oinq = _lead(db, other.id, None, phone="+919845099999")
    assert _post(client, oinq.id, _owner_headers(tenant_and_user), outcome="connected").status_code == 404

    g, inq = _lead(db, tenant.id, owner.id)
    inq.assigned_to = owner.id
    db.commit()
    _, concierge = _user(db, tenant.id, UserRole.CONCIERGE)
    assert _post(client, inq.id, concierge, outcome="connected").status_code == 404
    assert db.query(Call).filter(Call.ivr_provider == "manual").count() == 0
