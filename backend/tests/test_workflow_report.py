"""Lead workflows phase 4: the Report tab (funnel, per-agent speeds, missed calls returned, auto-WhatsApp replies, lost
reasons), the journey card on the lead page, and the backfill script."""
import uuid
from datetime import date, datetime, timedelta, timezone

from app.core.security import create_access_token, get_password_hash
from app.models.call import Call, CallDirection
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.lead_workflow import LeadJourney, PlaybookAction
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import lead_journey_tracker as journey
from app.services import workflow_report_service as rep

API = "/api/v1"


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _agent(db, tid, name, role=UserRole.CONCIERGE):
    u = User(id=str(uuid.uuid4()), tenant_id=tid, name=name, role=role, is_active=True,
             email=f"{uuid.uuid4().hex[:8]}@t.com", hashed_password=get_password_hash("pw-123456789"))
    db.add(u)
    db.commit()
    return u


def _lead(db, tid, owner, received, **milestones):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Guest", phone=f"+9198765{uuid.uuid4().int % 100000:05d}")
    db.add(guest)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, assigned_to=owner.id if owner else None,
                  created_at=received)
    db.add(inq)
    db.flush()
    db.add(LeadJourney(tenant_id=tid, inquiry_id=inq.id, guest_id=guest.id, received_at=received, auto_messages=0,
                       outcome=milestones.pop("outcome", "active"), lost_reason=milestones.pop("lost_reason", None),
                       **{k: received + timedelta(minutes=v) for k, v in milestones.items()}))
    db.commit()
    return guest, inq


def test_funnel_speeds_and_agents(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    asha, vik = _agent(db, tid, "Asha Kumar"), _agent(db, tid, "Vikram Rao")
    day = datetime.now(timezone.utc).replace(hour=6, minute=0, second=0, microsecond=0)   # 11:30 IST today
    _lead(db, tid, asha, day, first_viewed_at=4, first_call_attempt_at=9, first_human_contact_at=8, proposal_shared_at=300,
          outcome="won")
    _lead(db, tid, asha, day, first_viewed_at=6, first_human_contact_at=12)
    _lead(db, tid, vik, day, first_viewed_at=20, first_call_attempt_at=30, outcome="lost", lost_reason="budget_mismatch")
    _lead(db, tid, None, day)
    _lead(db, tid, asha, day - timedelta(days=60))                                       # outside the period
    out = rep.report(db, tid, date.today().replace(day=1) if day.date().day > 1 else day.date(), day.date())
    counts = {f["key"]: f["count"] for f in out["funnel"]}
    assert counts == {"received": 4, "seen": 3, "called": 2, "contacted": 2, "proposal": 1, "followed_up": 0, "sold": 1}
    assert out["summary"]["leads"] == 4 and out["summary"]["sold"] == 1
    assert out["summary"]["median_first_contact_minutes"] == 10
    a = {x["name"]: x for x in out["agents"]}
    assert a["Asha Kumar"]["leads"] == 2 and a["Asha Kumar"]["seen_minutes"] == 5 and a["Asha Kumar"]["proposal_minutes"] == 300
    assert a["Vikram Rao"]["top_lost_reason"] == "budget_mismatch" and a["Vikram Rao"]["first_contact_minutes"] is None
    assert out["agents"][-1]["name"] == "Unassigned"
    assert out["lost_reasons"] == [{"reason": "budget_mismatch", "count": 1}]
    assert out["biggest_drop"]["lost"] >= 1
    only_vik = rep.report(db, tid, day.date() - timedelta(days=2), day.date(), agent_id=vik.id)
    assert only_vik["summary"]["leads"] == 1


def test_missed_calls_returned_and_auto_replies(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    now = datetime.now(timezone.utc)
    guest, inq = _lead(db, tid, None, now - timedelta(hours=3))
    answered = Call(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, ivr_provider="vobiz", ivr_call_id="ok1",
                    direction=CallDirection.OUTBOUND, from_number="+91", to_number=guest.phone, duration_seconds=90,
                    ivr_dial_status="completed", created_at=now - timedelta(hours=2))
    db.add(answered)
    db.flush()
    for i, returned in enumerate((True, False)):
        db.add(Call(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, inquiry_id=inq.id, ivr_provider="vobiz",
                    ivr_call_id=f"m{i}", direction=CallDirection.INBOUND, from_number=guest.phone, to_number="+91",
                    duration_seconds=0, ivr_dial_status="no-answer", created_at=now - timedelta(hours=3),
                    recovered_by_call_id=answered.id if returned else None))
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv)
    db.flush()
    db.add(PlaybookAction(tenant_id=tid, playbook_key="missed_inbound_call", guest_id=guest.id, inquiry_id=inq.id,
                          action="wa_template", status="queued", payload={}, created_at=now - timedelta(hours=2)))
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.INBOUND,
                   channel=ChannelType.WHATSAPP, body="Yes please call", created_at=now - timedelta(hours=1)))
    db.commit()
    s = rep.report(db, tid, now.date() - timedelta(days=1), now.date() + timedelta(days=1))["summary"]
    assert (s["missed_calls"], s["missed_calls_returned"]) == (2, 1)
    assert (s["auto_messages"], s["auto_messages_replied"]) == (1, 1)


def test_journey_card_steps(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    owner = tenant_and_user["user"]
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Meera", phone="+919876500011")
    db.add(guest)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, assigned_to=owner.id,
                  created_at=datetime.now(timezone.utc) - timedelta(hours=2))
    db.add(inq)
    db.add(Call(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, ivr_provider="vobiz", ivr_call_id="j1",
                direction=CallDirection.OUTBOUND, from_number="+91", to_number=guest.phone, duration_seconds=0,
                ivr_dial_status="no-answer", created_at=datetime.now(timezone.utc) - timedelta(hours=1)))
    db.commit()
    journey.record_view(db, tid, inq.id, owner.id)
    out = journey.journey_out(db, tid, inq)
    steps = {s["key"]: s for s in out["steps"]}
    assert [s["key"] for s in out["steps"]] == ["received", "notified", "viewed", "called", "spoke", "contacted", "proposal",
                                                "followups", "outcome"]
    assert steps["viewed"]["done"] and "Test Owner opened" in steps["viewed"]["detail"]
    assert steps["called"]["done"] and steps["spoke"]["warn"] and steps["spoke"]["detail"] == "1 call, no answer"
    assert not steps["proposal"]["done"] and steps["outcome"]["detail"] == "Active"
    assert out["owner_name"] == "Test Owner"


def test_report_endpoint_roles_and_isolation(client, db, tenant_and_user, capabilities_seeded):
    tid = _tid(tenant_and_user)
    h = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    r = client.get(f"{API}/workflows/report", headers=h, params={"preset": "last_7d"})
    assert r.status_code == 200 and [f["key"] for f in r.json()["funnel"]][0] == "received"
    assert client.get(f"{API}/workflows/report", headers=h, params={"preset": "someday"}).status_code == 422
    agent = _agent(db, tid, "Asha")
    agent_h = {"Authorization": f"Bearer {create_access_token({'sub': agent.id, 'tenant_id': tid, 'role': 'concierge'})}"}
    assert client.get(f"{API}/workflows/report", headers=agent_h).status_code == 403
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    stranger = _agent(db, other.id, "Stranger")
    r = client.get(f"{API}/workflows/report", headers=h, params={"agent_id": stranger.id})
    assert r.status_code == 404


def test_backfill_dry_run_writes_nothing_and_apply_is_repeatable(db, tenant_and_user):
    import importlib.util
    from pathlib import Path
    tid = _tid(tenant_and_user)
    spec = importlib.util.spec_from_file_location("bf", Path(__file__).resolve().parents[1] / "scripts" / "backfill_lead_journeys.py")
    bf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bf)
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Old", phone="+919876500099")
    db.add(guest)
    db.flush()
    db.add(Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, created_at=datetime.now(timezone.utc) - timedelta(days=20)))
    db.commit()
    first = bf.run(db, tid, 180)
    assert first["enquiries"] == 1 and first["journeys_created"] == 1
    db.commit()
    again = bf.run(db, tid, 180)
    assert again["journeys_created"] == 0 and again["milestones_filled"] == 0
