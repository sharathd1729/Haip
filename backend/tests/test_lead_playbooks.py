"""Lead playbooks P1 (missed call -> WhatsApp), P2 (no answer -> WhatsApp), P7 ("Call me back" tap): guards, idempotency,
text vs template, the contact rule, tenant isolation. No real sends: the Celery send tasks and push are patched."""
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.api.v1.endpoints.messaging import TemplateCategory, TemplateStatus, WATemplate
from app.models.automation import AutomationRule
from app.models.call import Call, CallDirection
from app.models.consent import Consent
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.lead_workflow import PlaybookAction, PlaybookRun
from app.models.task import Task
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import lead_playbook_catalog as cat
from app.services import lead_playbook_engine as engine
from app.services import lead_playbook_settings as pb_settings
from app.services import wa_lead_pack as pack
from app.services.work_queue_service import human_touch

PHONE = "+919876543210"


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


@contextmanager
def _no_sends(in_hours=True):
    with patch("app.workers.tasks.send_whatsapp.send_whatsapp_template.delay") as tpl, \
         patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay") as txt, \
         patch("app.services.push_service.send_to_tenant") as push, \
         patch("app.core.tenant_tz.is_within_business_hours", return_value=in_hours):
        yield {"template": tpl, "text": txt, "push": push}


def _enable(db, tenant_id, *keys):
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    pb_settings.update(db, tenant, None, {"playbooks": {k: {"enabled": True} for k in keys}})
    db.commit()
    return tenant


def _approve(db, tenant_id, *names):
    for name in names:
        t = pack.BY_NAME[name]
        db.add(WATemplate(tenant_id=tenant_id, name=name, language="en", category=TemplateCategory.UTILITY,
                          status=TemplateStatus.APPROVED, components=[dict(c) for c in t["components"]]))
    db.commit()


def _lead(db, tenant_id, phone=PHONE, name="Kiran Rao", owner=None):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, phone=phone)
    db.add(guest)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, assigned_to=owner)
    db.add(inq)
    db.commit()
    return guest, inq


def _call(db, tenant_id, guest, inq, *, direction="inbound", answered=False, agent_id=None, at=None):
    call = Call(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, inquiry_id=inq.id if inq else None,
                ivr_provider="vobiz", ivr_call_id=f"c-{uuid.uuid4().hex[:10]}",
                direction=CallDirection.INBOUND if direction == "inbound" else CallDirection.OUTBOUND,
                from_number=guest.phone, to_number="+912271264296", duration_seconds=90 if answered else 0,
                ivr_dial_status="completed" if answered else "no-answer", agent_id=agent_id,
                created_at=at or datetime.now(timezone.utc))
    db.add(call)
    db.commit()
    return call


def _actions(db, tenant_id, **kw):
    return db.query(PlaybookAction).filter_by(tenant_id=tenant_id, **kw).order_by(PlaybookAction.created_at).all()


def _open_window(db, tenant_id, guest, minutes_ago=30):
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv)
    db.flush()
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id, direction=MessageDirection.INBOUND,
                   channel=ChannelType.WHATSAPP, body="Hi", created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)))
    db.commit()
    return conv


# ── P1 missed inbound call ──────────────────────────────────────────────────

def test_off_by_default_nothing_happens(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    guest, inq = _lead(db, tid)
    call = _call(db, tid, guest, inq)
    with _no_sends() as s:
        out = engine.on_call(db, tid, call.id)
    assert out["status"] == "off"
    assert db.query(PlaybookRun).filter_by(tenant_id=tid).count() == 0
    s["template"].assert_not_called()


def test_missed_call_sends_template_once_creates_task_and_push(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _enable(db, tid, cat.MISSED_INBOUND_CALL)
    _approve(db, tid, pack.MISSED_CALL)
    guest, inq = _lead(db, tid)
    call = _call(db, tid, guest, inq)
    with _no_sends() as s:
        out = engine.on_call(db, tid, call.id)
        again = engine.on_call(db, tid, call.id)
    assert out["status"] == "done" and again["status"] == "duplicate"
    sent = _actions(db, tid, action="wa_template")
    assert len(sent) == 1 and sent[0].status == "queued" and sent[0].template_name == pack.MISSED_CALL
    s["template"].assert_called_once()
    assert s["template"].call_args.kwargs["variables"] == ["Kiran", "Test Tenant", "shortly"]
    msg = db.query(Message).filter_by(id=sent[0].message_id).one()
    assert msg.sender_kind == "playbook" and msg.sent_autonomously is True
    assert msg.idempotency_key.startswith("pb:")
    task = db.query(Task).filter_by(tenant_id=tid, guest_id=guest.id).one()
    assert task.title.startswith("Call back — missed call from") and task.priority == "high"
    s["push"].assert_called_once()


def test_missed_call_inside_window_sends_plain_text(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _enable(db, tid, cat.MISSED_INBOUND_CALL)
    guest, inq = _lead(db, tid)
    _open_window(db, tid, guest)
    call = _call(db, tid, guest, inq)
    with _no_sends() as s:
        engine.on_call(db, tid, call.id)
    act = _actions(db, tid, action="wa_text")
    assert len(act) == 1 and act[0].status == "queued"
    s["text"].assert_called_once()
    s["template"].assert_not_called()
    assert "sorry we missed your call" in db.query(Message).filter_by(id=act[0].message_id).one().body


def test_unapproved_template_is_skipped_but_task_still_made(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _enable(db, tid, cat.MISSED_INBOUND_CALL)
    guest, inq = _lead(db, tid)
    call = _call(db, tid, guest, inq)
    with _no_sends(in_hours=False) as s:
        engine.on_call(db, tid, call.id)
    act = _actions(db, tid, action="wa_template")
    assert act[0].status == "skipped" and act[0].reason == "template not approved"
    task = db.query(Task).filter_by(tenant_id=tid, guest_id=guest.id).one()
    due = task.due_date if task.due_date.tzinfo else task.due_date.replace(tzinfo=timezone.utc)   # SQLite drops the zone
    local = due.astimezone(timezone(timedelta(hours=5, minutes=30)))
    assert (local.hour, local.minute) == (9, 30)                # after hours: next 9:30 am
    s["template"].assert_not_called()


def test_no_message_when_a_person_already_contacted_the_guest(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _enable(db, tid, cat.MISSED_INBOUND_CALL)
    _approve(db, tid, pack.MISSED_CALL)
    guest, inq = _lead(db, tid)
    call = _call(db, tid, guest, inq, at=datetime.now(timezone.utc) - timedelta(minutes=2))
    _call(db, tid, guest, inq, direction="outbound", answered=True)   # the agent called back and they spoke
    with _no_sends() as s:
        engine.on_call(db, tid, call.id)
    act = _actions(db, tid)
    assert [a.status for a in act] == ["skipped"]
    assert act[0].reason == "someone already contacted the guest after the call"
    assert db.query(Task).filter_by(tenant_id=tid, guest_id=guest.id).count() == 0
    s["template"].assert_not_called()


def test_guest_cap_one_message_for_two_missed_calls(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _enable(db, tid, cat.MISSED_INBOUND_CALL)
    _approve(db, tid, pack.MISSED_CALL)
    guest, inq = _lead(db, tid)
    first, second = _call(db, tid, guest, inq), _call(db, tid, guest, inq)
    with _no_sends() as s:
        engine.on_call(db, tid, first.id)
        engine.on_call(db, tid, second.id)
    statuses = [a.status for a in _actions(db, tid, action="wa_template")] + [a.reason for a in _actions(db, tid, action="wa_text")]
    assert statuses[0] == "queued"
    assert any("already got an automatic WhatsApp" in (r or "") for r in statuses[1:])
    assert s["template"].call_count == 1
    assert db.query(Task).filter_by(tenant_id=tid, guest_id=guest.id).count() == 1      # one open callback task, reused


@pytest.mark.parametrize("setup,reason", [
    ("stop", "the guest asked us to stop messaging them"),
    ("staff", "the number belongs to a team member"),
    ("rule", "an older automation rule also messages guests after calls; turn one of them off"),
    ("paused", "playbooks are paused on this lead"),
])
def test_guards_block_the_message(db, tenant_and_user, setup, reason):
    tid = _tid(tenant_and_user)
    _enable(db, tid, cat.MISSED_INBOUND_CALL)
    _approve(db, tid, pack.MISSED_CALL)
    guest, inq = _lead(db, tid)
    if setup == "stop":
        db.add(Consent(tenant_id=tid, guest_id=guest.id, channel="whatsapp", scope="marketing", granted=False,
                       recorded_at=datetime.now(timezone.utc).isoformat()))
    elif setup == "staff":
        tenant_and_user["user"].phone = PHONE
    elif setup == "rule":
        db.add(AutomationRule(id=str(uuid.uuid4()), tenant_id=tid, name="Old call WA", trigger="call_completed",
                              action="send_whatsapp_template", is_active=True))
    elif setup == "paused":
        from app.services import lead_journey_tracker as journey
        journey.ensure(db, inq).playbooks_paused_at = datetime.now(timezone.utc)
    db.commit()
    call = _call(db, tid, guest, inq)
    with _no_sends() as s:
        engine.on_call(db, tid, call.id)
    skipped = [a for a in _actions(db, tid) if a.action.startswith("wa_")]
    assert skipped and skipped[0].status == "skipped" and skipped[0].reason == reason
    s["template"].assert_not_called()


def test_booked_guest_gets_nothing(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _enable(db, tid, cat.MISSED_INBOUND_CALL)
    _approve(db, tid, pack.MISSED_CALL)
    guest, inq = _lead(db, tid)
    call = _call(db, tid, guest, inq)
    with _no_sends() as s, patch("app.services.work_queue_signals.booked_guests", return_value={guest.id}):
        engine.on_call(db, tid, call.id)
    act = _actions(db, tid)
    assert act[0].reason == "the guest already has a booking"
    assert db.query(Task).filter_by(tenant_id=tid, guest_id=guest.id).count() == 0
    s["template"].assert_not_called()


def test_personal_whatsapp_chat_in_progress_is_left_alone(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _enable(db, tid, cat.MISSED_INBOUND_CALL)
    _approve(db, tid, pack.MISSED_CALL)
    guest, inq = _lead(db, tid)
    db.add(Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True,
                        source="personal_bridge", last_message_at=datetime.now(timezone.utc).isoformat()))
    db.commit()
    call = _call(db, tid, guest, inq)
    with _no_sends() as s:
        engine.on_call(db, tid, call.id)
    act = [a for a in _actions(db, tid) if a.action.startswith("wa_")]
    assert act[0].status == "skipped" and "own WhatsApp" in act[0].reason
    s["template"].assert_not_called()


def test_answered_call_and_old_call_do_nothing(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _enable(db, tid, cat.MISSED_INBOUND_CALL)
    guest, inq = _lead(db, tid)
    answered = _call(db, tid, guest, inq, answered=True)
    old = _call(db, tid, guest, inq, at=datetime.now(timezone.utc) - timedelta(hours=2))
    with _no_sends():
        assert engine.on_call(db, tid, answered.id)["status"] == "answered"
        assert engine.on_call(db, tid, old.id)["status"] == "too_old"


def test_other_tenant_call_is_not_found(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    _enable(db, other.id, cat.MISSED_INBOUND_CALL)
    guest, inq = _lead(db, tid)
    call = _call(db, tid, guest, inq)
    with _no_sends():
        assert engine.on_call(db, other.id, call.id)["status"] == "no_call"
    assert db.query(PlaybookRun).count() == 0


# ── P2 no answer ────────────────────────────────────────────────────────────

def test_unanswered_outbound_sends_tried_calling_with_agent_name(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _enable(db, tid, cat.UNANSWERED_OUTBOUND)
    _approve(db, tid, pack.TRIED_CALLING)
    agent = tenant_and_user["user"]
    agent.name = "Asha Kumar"
    db.commit()
    guest, inq = _lead(db, tid)
    call = _call(db, tid, guest, inq, direction="outbound", agent_id=agent.id)
    with _no_sends() as s:
        engine.on_call(db, tid, call.id)
    assert s["template"].call_args.kwargs["variables"] == ["Kiran", "Asha", "Test Tenant"]
    assert db.query(Task).filter_by(tenant_id=tid, guest_id=guest.id).count() == 0     # ingest's own reminder covers it


# ── The contact rule ────────────────────────────────────────────────────────

def test_playbook_message_is_not_a_persons_contact(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _enable(db, tid, cat.MISSED_INBOUND_CALL)
    _approve(db, tid, pack.MISSED_CALL)
    guest, inq = _lead(db, tid)
    since = datetime.now(timezone.utc) - timedelta(minutes=5)
    call = _call(db, tid, guest, inq)
    with _no_sends():
        engine.on_call(db, tid, call.id)
    touched, _ = human_touch(db, tid, {guest.id: since})
    assert guest.id not in touched
    conv = db.query(Conversation).filter_by(tenant_id=tid, guest_id=guest.id).first()
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.OUTBOUND,
                   channel=ChannelType.WHATSAPP, body="Hi, Asha here", sender_kind="human"))
    db.commit()
    touched, _ = human_touch(db, tid, {guest.id: since})
    assert guest.id in touched


# ── P7 "Call me back" ───────────────────────────────────────────────────────

def test_call_me_back_tap_makes_task_and_short_reply_once(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _enable(db, tid, cat.MISSED_INBOUND_CALL)
    _approve(db, tid, pack.MISSED_CALL)
    guest, inq = _lead(db, tid)
    call = _call(db, tid, guest, inq)
    with _no_sends():
        engine.on_call(db, tid, call.id)
    sent = db.query(Message).filter_by(id=_actions(db, tid, action="wa_template")[0].message_id).one()
    sent.channel_message_id = "wamid.ours"
    db.query(Task).delete()
    conv = db.query(Conversation).filter_by(id=sent.conversation_id).one()
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.INBOUND,
                   channel=ChannelType.WHATSAPP, body=pack.BTN_CALL_ME_BACK))
    db.commit()
    assert engine.is_callback_tap(db, tid, "button", pack.BTN_CALL_ME_BACK, "wamid.ours")
    assert not engine.is_callback_tap(db, tid, "button", pack.BTN_CALL_ME_BACK, "wamid.someone-elses")
    assert not engine.is_callback_tap(db, tid, "text", pack.BTN_CALL_ME_BACK, "wamid.ours")
    with _no_sends() as s:
        out = engine.on_callback_tap(db, tid, guest.id, inq.id, "wamid.tap1", pack.BTN_CALL_ME_BACK)
        dup = engine.on_callback_tap(db, tid, guest.id, inq.id, "wamid.tap1", pack.BTN_CALL_ME_BACK)
    assert out["status"] == "done" and dup["status"] == "duplicate"
    task = db.query(Task).filter_by(tenant_id=tid, guest_id=guest.id).one()
    assert task.priority == "high" and "asked for a call" in task.title
    s["text"].assert_called_once()                               # "Sure Kiran, we'll call you shortly."
    s["push"].assert_called_once()


def test_stop_runs_and_settings_validation(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    guest, inq = _lead(db, tid)
    run = engine.start_run(db, tid, cat.MISSED_INBOUND_CALL, "call:x", inquiry_id=inq.id, guest_id=guest.id,
                           next_run_at=datetime.now(timezone.utc) + timedelta(hours=1))
    assert engine.start_run(db, tid, cat.MISSED_INBOUND_CALL, "call:x", inquiry_id=inq.id, guest_id=guest.id) is None
    assert engine.stop_runs(db, tid, inq.id, "the lead was closed") == 1
    db.commit()
    db.refresh(run)
    assert run.status == "stopped"
    tenant = db.query(Tenant).filter_by(id=tid).first()
    with pytest.raises(ValueError):
        pb_settings.update(db, tenant, None, {"playbooks": {cat.PROPOSAL_FOLLOWUP: {"mode": "loud"}}})
    with pytest.raises(ValueError):
        pb_settings.update(db, tenant, None, {"playbooks": {cat.MISSED_INBOUND_CALL: {"delay_seconds": 5}}})
    changes = pb_settings.update(db, tenant, None, {"playbooks": {cat.MISSED_INBOUND_CALL: {"enabled": True}}})
    assert changes == {"missed_inbound_call.enabled": {"from": False, "to": True}}
    assert pb_settings.playbook(tenant, cat.MISSED_INBOUND_CALL)["active"] is True
    pb_settings.update(db, tenant, None, {"enabled": False})
    assert pb_settings.playbook(tenant, cat.MISSED_INBOUND_CALL)["active"] is False


def test_callback_due_after_hours_is_next_morning():
    tenant = Tenant(id="t", name="T", slug="t", plan="growth")
    late = datetime(2026, 10, 20, 17, 0, tzinfo=timezone.utc)      # 22:30 IST
    early = datetime(2026, 10, 20, 1, 0, tzinfo=timezone.utc)      # 06:30 IST
    with patch("app.core.tenant_tz.is_within_business_hours", return_value=False):
        due, when = engine.callback_due(tenant, 15, late)
        assert when == "tomorrow morning" and due == datetime(2026, 10, 21, 4, 0, tzinfo=timezone.utc)
        due, when = engine.callback_due(tenant, 15, early)
        assert when == "this morning" and due == datetime(2026, 10, 20, 4, 0, tzinfo=timezone.utc)
    with patch("app.core.tenant_tz.is_within_business_hours", return_value=True):
        due, when = engine.callback_due(tenant, 15, late)
        assert when == "shortly" and due == late + timedelta(minutes=15)


def test_lead_pack_is_lint_clean():
    from app.services import wa_template_service as wts
    from app.services.template_linter import lint_template
    for t in pack.PACK:
        body = next(c for c in t["components"] if c["type"] == "BODY")
        samples = {str(i + 1): v for i, v in enumerate(body["example"]["body_text"][0])}
        findings = lint_template(body=body["text"], header=None, category="UTILITY", sample_values=samples)
        assert not [f for f in findings if f.level == "error"], (t["name"], findings)
        assert wts.validate_components(t["components"]) == [], t["name"]
        assert all(len(b["text"]) <= 25 for c in t["components"] if c["type"] == "BUTTONS" for b in c["buttons"])


def test_drain_runs_due_steps_and_fails_stale_claims(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _enable(db, tid, cat.MISSED_INBOUND_CALL)
    _approve(db, tid, pack.MISSED_CALL)
    guest, inq = _lead(db, tid)
    call = _call(db, tid, guest, inq)
    due = engine.start_run(db, tid, cat.MISSED_INBOUND_CALL, f"call:{call.id}", inquiry_id=inq.id, guest_id=guest.id,
                           context={"call_id": call.id})
    stale = engine.start_run(db, tid, cat.MISSED_INBOUND_CALL, "call:stale", inquiry_id=inq.id, guest_id=guest.id)
    stale.status, stale.updated_at = "claimed", datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()
    with _no_sends() as s:
        assert engine.drain_due(db) == 1
    db.refresh(due)
    db.refresh(stale)
    assert due.status == "done" and stale.status == "failed"
    s["template"].assert_called_once()


# ── P2 on a lead the system had closed (owner, 20 Oct 2026) ─────────────────

def _stages(db, tid):
    from app.models.pipeline_stage import PipelineStage
    from app.services.pipeline_stage_service import seed_default_pipeline_stages
    if not db.query(PipelineStage).filter_by(tenant_id=tid).count():
        seed_default_pipeline_stages(db, tid)
        db.commit()
    return {s.key: s for s in db.query(PipelineStage).filter_by(tenant_id=tid)}


def _closed(db, tid, inq, stage, by):
    from app.models.inquiry_360 import InquiryStageLog
    inq.stage_id = stage.id
    db.add(InquiryStageLog(tenant_id=tid, inquiry_id=inq.id, from_stage="active", to_stage=stage.key, changed_by=by,
                           changed_at=datetime.now(timezone.utc) - timedelta(days=10), reason="Bulk clear"))
    db.commit()


def test_agent_calling_a_lead_the_system_closed_reopens_it_and_still_whatsapps(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    st = _stages(db, tid)
    _enable(db, tid, cat.UNANSWERED_OUTBOUND)
    _approve(db, tid, pack.TRIED_CALLING)
    guest, inq = _lead(db, tid)
    _closed(db, tid, inq, st["lost"], by="system")
    call = _call(db, tid, guest, inq, direction="outbound", agent_id=tenant_and_user["user"].id)
    with _no_sends() as s:
        engine.on_call(db, tid, call.id)
    db.refresh(inq)
    assert inq.stage_id == st["active"].id
    assert s["template"].call_count == 1
    assert [(a.action, a.status) for a in _actions(db, tid, guest_id=guest.id)][:1] == [("reopen", "done")]


def test_a_lead_a_person_marked_lost_stays_lost_and_gets_nothing(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    st = _stages(db, tid)
    _enable(db, tid, cat.UNANSWERED_OUTBOUND)
    _approve(db, tid, pack.TRIED_CALLING)
    guest, inq = _lead(db, tid)
    _closed(db, tid, inq, st["lost"], by=tenant_and_user["user"].id)
    call = _call(db, tid, guest, inq, direction="outbound", agent_id=tenant_and_user["user"].id)
    with _no_sends() as s:
        engine.on_call(db, tid, call.id)
    db.refresh(inq)
    assert inq.stage_id == st["lost"].id and s["template"].call_count == 0
    assert [(a.action, a.reason) for a in _actions(db, tid, guest_id=guest.id)] == [("wa_text", "the lead is closed")]


def test_sold_and_missed_inbound_are_never_reopened(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    st = _stages(db, tid)
    _enable(db, tid, cat.UNANSWERED_OUTBOUND, cat.MISSED_INBOUND_CALL)
    guest, inq = _lead(db, tid)
    _closed(db, tid, inq, st["sold"], by="system")
    with _no_sends():
        engine.on_call(db, tid, _call(db, tid, guest, inq, direction="outbound").id)
    db.refresh(inq)
    assert inq.stage_id == st["sold"].id
    g2, inq2 = _lead(db, tid, phone="+919876500001")
    _closed(db, tid, inq2, st["lost"], by="system")
    with _no_sends():
        engine.on_call(db, tid, _call(db, tid, g2, inq2, direction="inbound").id)
    db.refresh(inq2)
    assert inq2.stage_id == st["lost"].id                      # a missed INBOUND call does not reopen (P2 only)
