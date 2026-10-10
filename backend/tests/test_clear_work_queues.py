"""scripts/clear_work_queues.py and the call-back "dismissed" marker."""
import importlib.util
import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from app.models.base import gen_uuid
from app.models.call import Call, CallDirection
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.property import Property, Stay
from app.models.stay_finance import StayServiceRequest
from app.models.task import Task
from app.models.tenant import Tenant
from app.services import work_queue_service

_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "clear_work_queues.py")


def _run(db, *argv):
    spec = importlib.util.spec_from_file_location("clear_work_queues", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with patch.object(mod, "SessionLocal", return_value=db), patch.object(db, "close"), patch.object(sys, "argv", ["x", *argv]):
        return mod.main()


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="Ratha", slug=f"rathaa-{uuid.uuid4().hex[:5]}", plan="growth", ivr_provider="vobiz")
    db.add(t)
    db.flush()
    return t


def _guest(db, tid):
    g = Guest(id=gen_uuid(), tenant_id=tid, name="Asha", phone=f"+9198{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    db.flush()
    return g


def _waiting_conversation(db, tid, age=timedelta(hours=5)):
    g = _guest(db, tid)
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv)
    db.flush()
    m = Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.INBOUND,
                channel=ChannelType.WHATSAPP, body="Is it available?")
    m.created_at = datetime.now(timezone.utc) - age
    db.add(m)
    return conv


def _missed_call(db, tid):
    g = _guest(db, tid)
    c = Call(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, ivr_provider="vobiz", ivr_call_id=str(uuid.uuid4()),
             direction=CallDirection.INBOUND, from_number="+910000000000", to_number="+910000000001",
             duration_seconds=0, ivr_dial_status="no-answer")
    db.add(c)
    db.flush()
    return c


def _overdue_task(db, tid, title="Call back Asha", due=timedelta(days=-3)):
    g = _guest(db, tid)
    t = Task(id=str(uuid.uuid4()), tenant_id=tid, title=title, guest_id=g.id, due_date=datetime.now(timezone.utc) + due)
    db.add(t)
    db.flush()
    return t


def _counts(db, tenant):
    return work_queue_service.counts(db, tenant, None)["counts"]


def test_dry_run_changes_nothing(db, capsys):
    t = _tenant(db)
    conv, call, task = _waiting_conversation(db, t.id), _missed_call(db, t.id), _overdue_task(db, t.id)
    db.commit()
    assert _run(db, "--tenant-slug", t.slug) == 0
    out = capsys.readouterr().out
    assert "Dry run only" in out and "Would close 1 conversations, dismiss 1 missed calls, mark 1 follow-ups done" in out
    for obj in (conv, call, task):
        db.refresh(obj)
    assert conv.is_open and call.callback_dismissed_at is None and not task.is_done


def test_apply_clears_the_three_queues_and_keeps_history(db, capsys):
    t = _tenant(db)
    conv, call, task = _waiting_conversation(db, t.id), _missed_call(db, t.id), _overdue_task(db, t.id)
    future = _overdue_task(db, t.id, "Next week", due=timedelta(days=5))       # not due soon: left alone
    db.commit()
    assert _counts(db, t)["reply"] == 1 and _counts(db, t)["callback"] == 1 and _counts(db, t)["followup"] == 1

    assert _run(db, "--tenant-slug", t.slug, "--apply") == 0
    for obj in (conv, call, task, future):
        db.refresh(obj)
    assert conv.is_open is False
    assert call.callback_dismissed_at is not None and call.recovered_by_call_id is None     # dismissed, NOT "called back"
    assert task.is_done and task.completed_at
    assert not future.is_done
    after = _counts(db, t)
    assert (after["reply"], after["callback"], after["followup"]) == (0, 0, 0)
    assert db.query(Message).filter_by(conversation_id=conv.id).count() == 1               # nothing deleted
    assert db.query(Call).filter_by(id=call.id).count() == 1
    assert "Needs you now" not in capsys.readouterr().out

    from app.models.audit_event import AuditEvent
    ev = db.query(AuditEvent).filter_by(tenant_id=t.id, action="work_queue.cleared").one()
    assert ev.payload == {"conversations_closed": 1, "missed_calls_dismissed": 1, "followups_done": 1}


def test_second_run_is_a_no_op(db, capsys):
    t = _tenant(db)
    _waiting_conversation(db, t.id)
    db.commit()
    _run(db, "--tenant-slug", t.slug, "--apply")
    capsys.readouterr()
    assert _run(db, "--tenant-slug", t.slug, "--apply") == 0
    assert "Closing 0 conversations, dismissing 0 missed calls, marking 0 follow-ups done" in capsys.readouterr().out


def test_service_request_follows_its_task(db):
    t = _tenant(db)
    prop = Property(id=gen_uuid(), tenant_id=t.id, name="C1", slug=f"c-{uuid.uuid4().hex[:5]}", type="villa", is_active=True)
    g = _guest(db, t.id)
    db.add(prop)
    db.flush()
    stay = Stay(id=gen_uuid(), tenant_id=t.id, guest_id=g.id, property_id=prop.id, check_in=date.today(), check_out=date.today() + timedelta(days=2))
    db.add(stay)
    db.flush()
    task = _overdue_task(db, t.id, "Extra bed")
    req = StayServiceRequest(tenant_id=t.id, stay_id=stay.id, title="Extra bed", task_id=task.id)
    db.add(req)
    db.commit()
    _run(db, "--tenant-slug", t.slug, "--apply")
    db.refresh(req)
    assert req.status == "done" and req.completed_at


def test_only_the_named_workspace_is_touched(db):
    t, other = _tenant(db), _tenant(db)
    _waiting_conversation(db, t.id)
    c2, call2, task2 = _waiting_conversation(db, other.id), _missed_call(db, other.id), _overdue_task(db, other.id)
    db.commit()
    _run(db, "--tenant-slug", t.slug, "--apply")
    for obj in (c2, call2, task2):
        db.refresh(obj)
    assert c2.is_open and call2.callback_dismissed_at is None and not task2.is_done


def test_lead_pipeline_queues_are_reported_not_faked(db, capsys):
    """call_new / draft / unassigned come from the lead pipeline: the script says so instead of pretending."""
    t = _tenant(db)
    db.commit()
    _run(db, "--tenant-slug", t.slug, "--apply")
    assert "All queues are at zero" in capsys.readouterr().out
    assert _run(db, "--tenant-slug", "nope") == 1


def test_dismissed_calls_leave_the_callback_lists(db, client, tenant_and_user):
    """The Calls page 'needs callback' view and the worklist both drop a dismissed call."""
    from app.services import worklist_service
    tid = tenant_and_user["tenant"].id
    tenant_and_user["tenant"].ivr_provider = "vobiz"
    call = _missed_call(db, tid)
    db.commit()
    h = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}

    assert worklist_service.missed_calls(db, tid, None)
    r = client.get("/api/v1/calls", params={"view": "needs_callback"}, headers=h)
    assert r.status_code == 200 and call.id in str(r.json())

    call.callback_dismissed_at = datetime.now(timezone.utc)
    db.commit()
    assert worklist_service.missed_calls(db, tid, None) == []
    assert call.id not in str(client.get("/api/v1/calls", params={"view": "needs_callback"}, headers=h).json())
