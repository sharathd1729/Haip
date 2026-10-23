"""Follow-up cadences (P5 proposal, P6 quiet lead, P8 win-back): triggers, every mode, the stop rules, send hours, the AI
draft guard, the autopilot alignment and the "Lost needs a reason" rule. No real sends: Celery sends, push and the LLM are
patched."""
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.api.v1.endpoints.messaging import TemplateCategory, TemplateStatus, WATemplate
from app.models.consent import Consent
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.inquiry_360 import InquiryQuote
from app.models.lead_workflow import PlaybookAction, PlaybookRun
from app.models.pipeline_stage import PipelineStage
from app.models.task import Task
from app.models.tenant import Tenant
from app.services import lead_followup_draft as drafts
from app.services import lead_followup_service as fu
from app.services import lead_playbook_catalog as cat
from app.services import lead_playbook_engine as engine
from app.services import lead_playbook_settings as pb_settings
from app.services import wa_lead_pack as pack


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


@contextmanager
def _env(send_ok=True):
    with patch("app.workers.tasks.send_whatsapp.send_whatsapp_template.delay") as tpl, \
         patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay") as txt, \
         patch("app.services.push_service.send_to_tenant") as push, \
         patch("app.workers.tasks.lead_playbooks.queue_draft") as draft, \
         patch.object(fu, "next_send_time", return_value=None if send_ok else datetime(2030, 1, 1, tzinfo=timezone.utc)):
        yield {"template": tpl, "text": txt, "push": push, "draft": draft}


def _setup(db, tid, key, mode, approve=()):
    tenant = db.query(Tenant).filter_by(id=tid).first()
    pb_settings.update(db, tenant, None, {"playbooks": {key: {"enabled": True, "mode": mode}}})
    for name in approve:
        t = pack.BY_NAME[name]
        db.add(WATemplate(tenant_id=tid, name=name, language="en",
                          category=TemplateCategory.MARKETING if t.get("category") == "MARKETING" else TemplateCategory.UTILITY,
                          status=TemplateStatus.APPROVED, components=[dict(c) for c in t["components"]]))
    db.commit()
    return tenant


def _lead(db, tid, owner=None, route="Coorg 48-hour retreat"):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Kiran Rao", phone="+919876543210")
    db.add(guest)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, assigned_to=owner, route_mentioned=route)
    db.add(inq)
    db.commit()
    return guest, inq


def _quote(db, tid, inq, hours_ago=7):
    q = InquiryQuote(tenant_id=tid, inquiry_id=inq.id, amount=45000, shared_via="sent",
                     shared_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
                     valid_until=datetime.now(timezone.utc) + timedelta(days=2))
    db.add(q)
    db.commit()
    return q


def _window(db, tid, guest, minutes_ago=600):
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv)
    db.flush()
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.INBOUND,
                   channel=ChannelType.WHATSAPP, body="Hi, what are the dates?",
                   created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)))
    db.commit()
    return conv


def _run(db, tid, key):
    return db.query(PlaybookRun).filter_by(tenant_id=tid, playbook_key=key).one()


def _fire(db, run):
    run.next_run_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    return engine.run_step(db, run)


# ── P5 proposal follow-up ───────────────────────────────────────────────────

def test_off_by_default_no_runs(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _, inq = _lead(db, tid)
    _quote(db, tid, inq)
    tenant = db.query(Tenant).filter_by(id=tid).first()
    assert fu.sweep_tenant(db, tenant) == {k: 0 for k in cat.FOLLOWUP_PLAYBOOKS}


def test_proposal_runs_all_four_steps_in_tasks_mode(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    owner = tenant_and_user["user"]
    tenant = _setup(db, tid, cat.PROPOSAL_FOLLOWUP, "tasks")
    guest, inq = _lead(db, tid, owner=owner.id)
    q = _quote(db, tid, inq)
    assert fu.sweep_tenant(db, tenant)[cat.PROPOSAL_FOLLOWUP] == 1
    assert fu.sweep_tenant(db, tenant)[cat.PROPOSAL_FOLLOWUP] == 0          # same quote: no second run
    run = _run(db, tid, cat.PROPOSAL_FOLLOWUP)
    base = q.shared_at if q.shared_at.tzinfo else q.shared_at.replace(tzinfo=timezone.utc)
    with _env() as s:
        for _ in range(4):
            _fire(db, run)
            db.refresh(run)
    tasks = db.query(Task).filter_by(tenant_id=tid, playbook_run_id=run.id).order_by(Task.created_at).all()
    assert [t.kind for t in tasks] == ["followup", "call", "followup", "decide"]
    assert all(t.assigned_to == owner.id for t in tasks)
    assert tasks[1].priority == "high" and "Sold, or Lost" in tasks[3].title
    assert run.status == "done" and run.step == 4
    s["template"].assert_not_called()
    s["text"].assert_not_called()


def test_drafts_mode_queues_an_ai_draft_in_window_and_a_template_task_outside(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    tenant = _setup(db, tid, cat.PROPOSAL_FOLLOWUP, "drafts")
    guest, inq = _lead(db, tid)
    _quote(db, tid, inq)
    fu.sweep_tenant(db, tenant)
    run = _run(db, tid, cat.PROPOSAL_FOLLOWUP)
    with _env() as s:
        _fire(db, run)                                                       # window closed
    task = db.query(Task).filter_by(tenant_id=tid, playbook_run_id=run.id).one()
    assert "'Proposal follow-up' template" in task.title
    s["draft"].assert_not_called()

    guest2, inq2 = _lead(db, tid)
    _quote(db, tid, inq2)
    conv = _window(db, tid, guest2, minutes_ago=8 * 60)                      # wrote 8 h ago: before the quote
    fu.sweep_tenant(db, tenant)
    run2 = db.query(PlaybookRun).filter_by(tenant_id=tid, guest_id=guest2.id).one()
    with _env() as s:
        _fire(db, run2)
    s["draft"].assert_called_once()
    args = s["draft"].call_args.args
    assert args[1] == run2.id and args[3] == conv.id and "Coorg 48-hour retreat" in args[4]


def test_make_draft_stores_a_pending_draft_and_rejects_prices(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _setup(db, tid, cat.PROPOSAL_FOLLOWUP, "drafts")
    guest, inq = _lead(db, tid)
    conv = _window(db, tid, guest)
    run = engine.start_run(db, tid, cat.PROPOSAL_FOLLOWUP, "quote:x", inquiry_id=inq.id, guest_id=guest.id,
                           context={"base": datetime.now(timezone.utc).isoformat()})
    with patch.object(drafts, "_complete", new=_coro("Hi Kiran, it's just ₹45,000 for two nights!")), \
         patch("app.services.push_service.send_to_tenant"):
        msg_id = fu.make_draft(db, tid, run.id, "nudge", conv.id, "Fixed words.")
    msg = db.query(Message).filter_by(id=msg_id).one()
    assert msg.is_ai_generated is True and msg.was_approved is None and msg.body == "Fixed words."
    assert msg.channel_metadata["draft_source"] == "fixed"
    with patch.object(drafts, "_complete", new=_coro("Hi Kiran, did the proposal reach you? Happy to adjust it.")), \
         patch("app.services.push_service.send_to_tenant"):
        msg2 = db.query(Message).filter_by(id=fu.make_draft(db, tid, run.id, "nudge", conv.id, "Fixed words.")).one()
    assert msg2.body.startswith("Hi Kiran, did the proposal") and msg2.channel_metadata["draft_source"] == "ai"
    assert db.query(Task).filter_by(tenant_id=tid, playbook_run_id=run.id, kind="followup").count() == 2
    assert drafts.check_reply("") == "empty reply" and drafts.check_reply("x" * 700) == "too long"


async def _async(value):
    return value


def _coro(value):
    return lambda *_a, **_k: _async(value)


def test_autopilot_sends_the_fixed_template_or_falls_back_to_a_task(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    tenant = _setup(db, tid, cat.PROPOSAL_FOLLOWUP, "autopilot", approve=(pack.QUOTE_FOLLOWUP,))
    guest, inq = _lead(db, tid)
    _quote(db, tid, inq)
    fu.sweep_tenant(db, tenant)
    run = _run(db, tid, cat.PROPOSAL_FOLLOWUP)
    with _env() as s:
        _fire(db, run)
    s["template"].assert_called_once()
    assert s["template"].call_args.kwargs["template_name"] == pack.QUOTE_FOLLOWUP
    assert s["template"].call_args.kwargs["variables"][:2] == ["Kiran", "Coorg 48-hour retreat"]
    act = db.query(PlaybookAction).filter_by(tenant_id=tid, run_id=run.id, action="wa_template").one()
    msg = db.query(Message).filter_by(id=act.message_id).one()
    assert msg.sender_kind == "playbook" and msg.sent_autonomously is True

    # A week later (the 20 h gap between automatic messages has passed), the day-7 last call has no approved template
    # here: a task instead of a send.
    act.created_at = datetime.now(timezone.utc) - timedelta(days=7)
    run.step = 2
    db.commit()
    with _env() as s:
        _fire(db, run)
    assert s["template"].call_count == 0
    assert db.query(Task).filter(Task.playbook_run_id == run.id, Task.title.like("%not approved yet%")).count() == 1


@pytest.mark.parametrize("what,reason", [
    ("reply", "the guest replied"),
    ("closed", "the lead was closed"),
    ("off", "the playbook was switched off"),
])
def test_runs_stop_for_good(db, tenant_and_user, what, reason):
    tid = _tid(tenant_and_user)
    tenant = _setup(db, tid, cat.PROPOSAL_FOLLOWUP, "tasks")
    guest, inq = _lead(db, tid)
    _quote(db, tid, inq)
    fu.sweep_tenant(db, tenant)
    run = _run(db, tid, cat.PROPOSAL_FOLLOWUP)
    if what == "reply":
        _window(db, tid, guest, minutes_ago=30)
    elif what == "closed":
        lost = PipelineStage(tenant_id=tid, key="lost", label="Lost", category="valid", is_closed_lost=True, order=9)
        db.add(lost)
        db.flush()
        inq.stage_id = lost.id
        db.commit()
    else:
        pb_settings.update(db, tenant, None, {"playbooks": {cat.PROPOSAL_FOLLOWUP: {"enabled": False}}})
        db.commit()
    with _env():
        out = _fire(db, run)
    assert out["status"] == "stopped" and out["reason"] == reason
    assert db.query(Task).filter_by(tenant_id=tid, playbook_run_id=run.id).count() == 0


def test_message_waits_for_send_hours(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    tenant = _setup(db, tid, cat.PROPOSAL_FOLLOWUP, "tasks")
    _, inq = _lead(db, tid)
    _quote(db, tid, inq)
    fu.sweep_tenant(db, tenant)
    run = _run(db, tid, cat.PROPOSAL_FOLLOWUP)
    with _env(send_ok=False):
        out = _fire(db, run)
    db.refresh(run)
    assert out["status"] == "waiting" and run.step == 0 and run.status == "scheduled"
    t = Tenant(id="t", name="T", slug="t", plan="growth")
    late = datetime(2026, 10, 20, 16, 0, tzinfo=timezone.utc)              # 21:30 IST
    assert fu.next_send_time(t, late) == datetime(2026, 10, 21, 4, 0, tzinfo=timezone.utc)
    assert fu.next_send_time(t, datetime(2026, 10, 20, 6, 0, tzinfo=timezone.utc)) is None


# ── P6 quiet lead, P8 win-back ──────────────────────────────────────────────

def test_quiet_lead_starts_from_the_queue_but_not_while_a_proposal_runs(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    tenant = _setup(db, tid, cat.QUIET_LEAD_NURTURE, "tasks")
    pb_settings.update(db, tenant, None, {"playbooks": {cat.PROPOSAL_FOLLOWUP: {"enabled": True, "mode": "tasks"}}})
    db.commit()
    g1, i1 = _lead(db, tid)
    g2, i2 = _lead(db, tid)
    _quote(db, tid, i2)
    since = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    items = [{"kind": "no_reply", "guest_id": g.id, "inquiry_id": i.id, "since": since} for g, i in ((g1, i1), (g2, i2))]
    with patch("app.services.work_queue_service.build", return_value={"items": items}):
        started = fu.sweep_tenant(db, tenant)
    assert started[cat.QUIET_LEAD_NURTURE] == 1
    run = _run(db, tid, cat.QUIET_LEAD_NURTURE)
    assert run.guest_id == g1.id
    with _env():
        _fire(db, run)
    assert db.query(Task).filter_by(playbook_run_id=run.id).one().title.startswith("Follow up with Kiran")


def test_win_back_only_with_offer_consent_and_once_in_90_days(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    tenant = _setup(db, tid, cat.LOST_REENGAGE, "autopilot", approve=(pack.REENGAGE,))
    lost = PipelineStage(tenant_id=tid, key="lost", label="Lost", category="valid", is_closed_lost=True, order=9)
    db.add(lost)
    db.flush()
    yes_g, yes_i = _lead(db, tid)
    no_g, no_i = _lead(db, tid)
    for inq in (yes_i, no_i):
        inq.stage_id, inq.current_stage_entered_at = lost.id, datetime.now(timezone.utc) - timedelta(days=50)
    db.add(Consent(tenant_id=tid, guest_id=yes_g.id, channel="whatsapp", scope="marketing", granted=True,
                   recorded_at=datetime.now(timezone.utc).isoformat()))
    db.commit()
    assert fu.sweep_tenant(db, tenant)[cat.LOST_REENGAGE] == 1
    run = _run(db, tid, cat.LOST_REENGAGE)
    assert run.guest_id == yes_g.id
    with _env() as s:
        _fire(db, run)
    assert s["template"].call_args.kwargs["template_name"] == pack.REENGAGE
    yes_i.id  # noqa: B018 -- the same guest is not re-engaged again within 90 days
    assert fu._reengaged_recently(db, tid, yes_g.id, datetime.now(timezone.utc))


# ── Rules around the cadences ───────────────────────────────────────────────

def test_autopilot_waits_for_the_proposal_follow_up(db, tenant_and_user):
    from app.services.lead_autopilot_service import _with_followups
    tid = _tid(tenant_and_user)
    settings = {"quote_silence_days": 7}
    assert _with_followups(db, tid, settings)["quote_silence_days"] == 7
    _setup(db, tid, cat.PROPOSAL_FOLLOWUP, "drafts")
    assert _with_followups(db, tid, settings)["quote_silence_days"] == 9


def test_marking_lost_needs_a_reason(client, db, tenant_and_user, capabilities_seeded):
    tid = _tid(tenant_and_user)
    h = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    active = PipelineStage(tenant_id=tid, key="active", label="Active", category="valid", order=3)
    lost = PipelineStage(tenant_id=tid, key="lost", label="Lost", category="valid", is_closed_lost=True, order=9)
    db.add_all([active, lost])
    db.flush()
    _, inq = _lead(db, tid)
    inq.stage_id = active.id
    db.commit()
    r = client.patch(f"/api/v1/inquiries/{inq.id}", headers=h, json={"stage_id": lost.id})
    assert r.status_code == 422 and "why the lead was lost" in r.json()["detail"]["message"]
    r = client.patch(f"/api/v1/inquiries/{inq.id}", headers=h, json={"stage_id": lost.id, "lost_reason": "budget_mismatch"})
    assert r.status_code == 200


def test_followup_draft_route_and_templates():
    from app.adapters.llm import _TASK_ROUTES
    from app.core.prompt_versions import PROMPT_VERSIONS
    assert _TASK_ROUTES["lead_followup_draft"] == ("nvidia", "openai/gpt-oss-20b")
    assert PROMPT_VERSIONS["lead_followup_draft"] == "lead-followup-draft-v2"
    assert pack.BY_NAME[pack.REENGAGE]["category"] == "MARKETING"
