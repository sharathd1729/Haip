"""When lead work is over its reminders go (lead_task_closer, 22 Oct 2026): closed enquiries are never "at risk" nor on My
day's follow-ups, a stage move to won/lost/unsuitable closes the lead's open tasks through BOTH stage paths, and a call
that connected settles the guest's call-backs. Every test builds a second workspace that must stay untouched."""
import uuid
from datetime import datetime, timedelta, timezone

from app.models.audit_event import AuditEvent
from app.models.call import Call, CallDirection
from app.models.inquiry import InquiryStage
from app.models.task import Task
from app.services import inquiry_service, lead_task_closer, work_queue_service as wq
from tests.services.test_work_queue_signals import TODAY, _contacted, _lead, _msg, _stage, _tenant

NOW = datetime.now(timezone.utc)


def _task(db, tid, title, guest=None, inquiry=None, hours_ago=3, kind=None):
    t = Task(id=str(uuid.uuid4()), tenant_id=tid, title=title, guest_id=guest.id if guest else None,
             inquiry_id=inquiry.id if inquiry else None, due_date=NOW - timedelta(hours=hours_ago), is_done=False, kind=kind)
    db.add(t); db.flush()
    return t


def _call(db, tid, guest, direction, hours_ago, status, duration=60, human=None):
    c = Call(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, ivr_provider="vobiz", ivr_call_id=uuid.uuid4().hex[:12],
             direction=direction, from_number=guest.phone, to_number="+918000000000", duration_seconds=duration,
             ivr_dial_status=status, human_disposition=human, created_at=NOW - timedelta(hours=hours_ago))
    db.add(c); db.flush()
    return c


def _titles(res):
    return {i["title"] for i in res["items"]} | {t["title"] for i in res["items"] for t in i["tasks"]}


# ── the queue ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_an_unsuitable_lead_is_never_at_risk_nor_a_follow_up(db):
    t, other = _tenant(db), _tenant(db)
    active = _stage(db, t.id, "active", "valid")
    unsuitable = _stage(db, t.id, "unsuitable", "valid")
    soon = (TODAY + timedelta(days=10)).isoformat()
    warm = {"temperature": {"value": "warm"}}
    for name, stage in (("Open one", active), ("Unsuitable one", unsuitable)):
        g, i, c = _lead(db, t.id, name, stage=stage, check_in=soon, ai_analysis=warm)
        _msg(db, t.id, c, "inbound", 120)
        _contacted(db, t.id, c, hours_ago=100)
        _task(db, t.id, f"Follow up {name}", guest=g, inquiry=i)
    db.commit()
    res = wq.build(db, t, scope_user_id=None)
    assert "Follow up Unsuitable one" not in _titles(res)
    assert {i["title"] for i in res["items"] if "at_risk" in i["flags"]} == {"Open one"}
    assert res["flags"]["at_risk"] == 1
    assert wq.build(db, other, scope_user_id=None)["flags"]["at_risk"] == 0


def test_a_sold_lead_keeps_its_booking_reminder_but_not_its_call_back(db):
    t = _tenant(db)
    sold = _stage(db, t.id, "sold", "valid", won=True)
    g, i, _ = _lead(db, t.id, "Booked guest", stage=sold)
    _task(db, t.id, "Call back — no answer from Booked guest", guest=g, inquiry=i)
    _task(db, t.id, "Collect the ₹20,000 balance from Booked guest (RB-1)", guest=g, inquiry=i)
    db.commit()
    titles = _titles(wq.build(db, t, scope_user_id=None))
    assert "Collect the ₹20,000 balance from Booked guest (RB-1)" in titles
    assert "Call back — no answer from Booked guest" not in titles


def test_closed_states_reads_stage_legacy_enum_and_qualification(db):
    t, other = _tenant(db), _tenant(db)
    active, lost = _stage(db, t.id, "active", "valid"), _stage(db, t.id, "lost", "valid", lost=True)
    _, open_i, _ = _lead(db, t.id, "Open", stage=active)
    _, lost_i, _ = _lead(db, t.id, "Lost", stage=lost)
    _, junk_i, _ = _lead(db, t.id, "Junk", stage=active, qualification_status="unqualified")
    _, legacy_i, _ = _lead(db, t.id, "Legacy")
    legacy_i.stage = InquiryStage.BOOKED
    db.commit()
    states = lead_task_closer.closed_states(db, t.id, [open_i.id, lost_i.id, junk_i.id, legacy_i.id])
    assert states == {lost_i.id: "closed", junk_i.id: "closed", legacy_i.id: "won"}
    assert lead_task_closer.closed_states(db, other.id, [lost_i.id]) == {}


# ── stage moves close the lead's tasks (both paths) ───────────────────────────────────────────────────────────

def test_moving_a_lead_to_lost_by_stage_id_closes_its_open_tasks_with_an_audit(db, tenant_and_user):
    t = _tenant(db)
    active, lost = _stage(db, t.id, "active", "valid"), _stage(db, t.id, "lost", "valid", lost=True)
    active.order, lost.order = 1, 5
    g, i, _ = _lead(db, t.id, "Ravi", stage=active)
    follow = _task(db, t.id, "Follow up Ravi", guest=g, inquiry=i, kind="followup")
    callback = _task(db, t.id, "Callback requested — Ravi", guest=g)          # about the guest, no enquiry on it
    other_g, other_i, _ = _lead(db, t.id, "Someone else", stage=active)
    untouched = _task(db, t.id, "Follow up Someone else", guest=other_g, inquiry=other_i)
    db.commit()
    inquiry_service.update_stage_by_id(db, tenant_id=t.id, inquiry_id=i.id, new_stage_id=lost.id, actor_user_id=None,
                                       actor_role="owner")
    db.commit()
    for task in (follow, callback, untouched):
        db.refresh(task)
    assert follow.is_done and follow.completed_at is not None and callback.is_done
    assert untouched.is_done is False
    audited = {e.target_id for e in db.query(AuditEvent).filter_by(tenant_id=t.id, action="task.auto_closed")}
    assert audited == {follow.id, callback.id}


def test_selling_a_lead_by_stage_id_closes_only_the_lead_chasing_tasks(db):
    t = _tenant(db)
    active, sold = _stage(db, t.id, "active", "valid"), _stage(db, t.id, "sold", "valid", won=True)
    active.order, sold.order = 1, 6
    g, i, _ = _lead(db, t.id, "Meera", stage=active)
    call_task = _task(db, t.id, "Call back — missed call from Meera", guest=g, inquiry=i)
    decide = _task(db, t.id, "Decide on Meera", guest=g, inquiry=i, kind="decide")
    note = _task(db, t.id, "Send Meera the pickup map", guest=g, inquiry=i)
    db.commit()
    inquiry_service.update_stage_by_id(db, tenant_id=t.id, inquiry_id=i.id, new_stage_id=sold.id, actor_user_id=None,
                                       actor_role="owner")
    db.commit()
    for task in (call_task, decide, note):
        db.refresh(task)
    assert call_task.is_done and decide.is_done and note.is_done is False


def test_the_legacy_stage_path_closes_tasks_too(db):
    t = _tenant(db)
    g, i, _ = _lead(db, t.id, "Old path")
    task = _task(db, t.id, "Follow up Old path", guest=g, inquiry=i)
    db.commit()
    inquiry_service.update_stage(db, tenant_id=t.id, inquiry_id=i.id, new_stage=InquiryStage.LOST, actor_user_id=None,
                                 actor_role="owner")
    db.commit()
    db.refresh(task)
    assert task.is_done is True


# ── a connected call settles call-backs ───────────────────────────────────────────────────────────────────────

def test_a_connected_call_closes_call_backs_and_dismisses_the_missed_calls(db):
    t, other = _tenant(db), _tenant(db)
    g, i, _ = _lead(db, t.id, "Anita")
    missed = _call(db, t.id, g, CallDirection.INBOUND, 5, "no-answer", duration=0)
    tasks = [_task(db, t.id, title, guest=g, inquiry=i) for title in
             ("Call back — missed call from Anita", "Callback requested — Anita", "Call back — no answer from Anita")]
    keep = _task(db, t.id, "Send Anita the brochure", guest=g, inquiry=i)
    og, _, _ = _lead(db, other.id, "Elsewhere")
    other_missed = _call(db, other.id, og, CallDirection.INBOUND, 5, "no-answer", duration=0)
    back = _call(db, t.id, g, CallDirection.OUTBOUND, 1, "completed", duration=120)
    db.commit()
    out = lead_task_closer.resolve_callbacks(db, t.id, back)
    db.commit()
    assert out == {"tasks": 3, "calls": 1}
    for x in (*tasks, keep, missed, other_missed):
        db.refresh(x)
    assert all(x.is_done for x in tasks) and keep.is_done is False
    assert missed.callback_dismissed_at is not None and missed.recovered_by_call_id == back.id
    assert other_missed.callback_dismissed_at is None


def test_a_call_that_did_not_connect_settles_nothing(db):
    t = _tenant(db)
    g, i, _ = _lead(db, t.id, "Kiran")
    missed = _call(db, t.id, g, CallDirection.INBOUND, 5, "no-answer", duration=0)
    task = _task(db, t.id, "Call back — missed call from Kiran", guest=g, inquiry=i)
    tried = _call(db, t.id, g, CallDirection.OUTBOUND, 1, "no-answer", duration=25)
    # Duration alone is never proof: an inbound call with the greeting's length and no other signal.
    unsure = _call(db, t.id, g, CallDirection.INBOUND, 1, None, duration=40)
    db.commit()
    assert lead_task_closer.resolve_callbacks(db, t.id, tried) == {"tasks": 0, "calls": 0}
    assert lead_task_closer.resolve_callbacks(db, t.id, unsure) == {"tasks": 0, "calls": 0}
    db.refresh(task); db.refresh(missed)
    assert task.is_done is False and missed.callback_dismissed_at is None


def test_an_answered_callback_ingested_from_the_ivr_closes_the_reminder(db, tenant_and_user, monkeypatch):
    from tests.test_call_ingest_callback_task import _payload, _run_ingest, _tenant_id
    tid = _tenant_id(tenant_and_user)
    first = _run_ingest(monkeypatch, db, tid, _payload())                           # nobody picked up -> reminder
    call = db.query(Call).filter_by(id=first["call_id"]).one()
    reminder = db.query(Task).filter_by(tenant_id=tid, guest_id=call.guest_id, is_done=False).one()
    _run_ingest(monkeypatch, db, tid, _payload(ivr_dial_status="completed", duration_seconds=90))
    db.refresh(reminder)
    assert reminder.is_done is True
