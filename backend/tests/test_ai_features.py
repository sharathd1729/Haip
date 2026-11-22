"""Settings > AI switches, step 1 (docs/ai/AI_SWITCHES_SPEC.md): the backend gate.

* every routed LLM task maps to a feature (TASK_FEATURE), so a new task without one fails here;
* a switched-off feature makes NO provider call and writes NO usage_events row (the gate inside get_llm's MeteredAdapter);
* read-only sources (personal WhatsApp, Meta lead forms) never get an AI reply: no draft, no concierge_* usage row, through
  any path (webhook/concierge task, reply safety net, automation action, the "write a draft" button);
* Instagram comments follow their own reply mode (default off); lead summaries, personal-WhatsApp summaries and call
  analysis are skipped before any job when off.
Celery queues and providers are faked.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from app.adapters.llm import _TASK_ROUTES
from app.adapters.llm.metered import MeteredAdapter
from app.adapters.llm.scope import llm_scope
from app.models.call import Call
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.services import ai_features, ai_mode_service
from app.services.ai_features import AIFeatureDisabled

pytestmark = pytest.mark.usefixtures("capabilities_seeded")


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────────────


class _Inner:
    """A provider adapter that counts requests."""

    provider = "fake"
    _default_model = "fake-1"

    def __init__(self, reply=None):
        self.calls = 0
        self.reply = reply or {"text": "ok", "input_tokens": 1, "output_tokens": 1}

    async def complete(self, **kwargs):
        self.calls += 1
        return self.reply


class _NoClose:
    """The test session for code that opens its own SessionLocal(), without letting it close the test's session."""

    def __init__(self, db):
        self._db = db

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._db, name)


@pytest.fixture()
def rows(db, monkeypatch):
    """Every usage_events row the meter would write; the gate's settings read goes through the test session, uncached."""
    out = []
    monkeypatch.setattr("app.adapters.llm.metered.route", lambda row: out.append(row))
    monkeypatch.setattr("app.core.database.SessionLocal", lambda: _NoClose(db))
    monkeypatch.setattr("app.core.cache.get_cached", lambda key: None)
    monkeypatch.setattr("app.core.cache.set_cached", lambda *a, **k: None)
    return out


def _tenant(db, **cols):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth", **cols)
    db.add(t)
    db.commit()
    return t


def _call(task, tenant_id=None):
    inner = _Inner()
    asyncio.run(MeteredAdapter(inner, task, tenant_id).complete(system_prompt="s", user_message="u"))
    return inner


def _conv(db, tid, channel=ChannelType.WHATSAPP, source=None, ai_mode=None):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="G", phone=f"+9198{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    db.flush()
    c = Conversation(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        guest_id=g.id,
        channel=channel,
        is_open=True,
        source=source,
        ai_mode=ai_mode,
    )
    db.add(c)
    db.flush()
    return c


def _msg(db, tid, c, minutes=1, body="Is it free this weekend?", **kw):
    m = Message(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        conversation_id=c.id,
        direction="inbound",
        channel=getattr(c.channel, "value", c.channel),
        body=body,
        created_at=datetime.now(UTC) - timedelta(minutes=minutes),
        **kw,
    )
    db.add(m)
    db.flush()
    return m


# ── 1. the task -> feature map ───────────────────────────────────────────────────────────────────────────


def test_every_routed_task_has_a_feature():
    missing = sorted(set(_TASK_ROUTES) - set(ai_features.TASK_FEATURE))
    assert not missing, f"add these tasks to services/ai_features.TASK_FEATURE: {missing}"


def test_every_feature_in_the_map_is_known():
    known = set(ai_features.DEFAULTS) | set(ai_features.UNSWITCHED) | {ai_features.REPLIES}
    assert set(ai_features.TASK_FEATURE.values()) <= known


def test_unrouted_task_names_fall_back_by_prefix():
    assert ai_features.feature_for("ask_haip_rca") == "ask_haip"
    assert ai_features.feature_for("marketing_new_thing") == "marketing"
    assert ai_features.feature_for("direct:gemini") == "core"


# ── 2. the gate inside get_llm (MeteredAdapter) ──────────────────────────────────────────────────────────

GATED = [
    ("call_analysis", "call_analysis"),
    ("call_analysis", "deep_reason"),
    ("lead_summaries", "lead_summary"),
    ("lead_autopilot", "lead_stage_classify"),
    ("briefings", "analyst_brief"),
    ("briefings", "chief_explain"),
]


@pytest.mark.parametrize("feature,task", GATED)
def test_a_switched_off_feature_makes_no_provider_call_and_no_usage_row(db, rows, feature, task):
    t = _tenant(db, ai_features={feature: False})
    inner = _Inner()
    with pytest.raises(AIFeatureDisabled):
        asyncio.run(MeteredAdapter(inner, task, t.id).complete(system_prompt="s", user_message="u"))
    assert inner.calls == 0 and rows == []


@pytest.mark.parametrize("feature,task", GATED)
def test_a_feature_left_at_its_default_runs_and_is_metered(db, rows, feature, task):
    t = _tenant(db)
    assert _call(task, t.id).calls == 1
    assert len(rows) == 1 and rows[0]["meta"]["task"] == task


def test_the_tenant_comes_from_the_llm_scope_when_the_call_site_passes_none(db, rows):
    t = _tenant(db, ai_features={"lead_summaries": False})
    with llm_scope(tenant_id=t.id, module="leads"), pytest.raises(AIFeatureDisabled):
        _call("lead_summary")
    assert rows == []


def test_one_workspace_switching_off_does_not_touch_another(db, rows):
    off, on = _tenant(db, ai_features={"call_analysis": False}), _tenant(db)
    with pytest.raises(AIFeatureDisabled):
        _call("call_analysis", off.id)
    assert _call("call_analysis", on.id).calls == 1
    assert [r["tenant_id"] for r in rows] == [on.id]


def test_reply_tasks_stop_only_when_every_reply_mode_is_off(db, rows):
    all_off = _tenant(db, wa_ai_mode_default="off", ig_ai_mode_default="off", ig_comment_ai_mode_default="off")
    with pytest.raises(AIFeatureDisabled):
        _call("concierge_draft", all_off.id)
    wa_on = _tenant(db, wa_ai_mode_default="shadow", ig_ai_mode_default="off", ig_comment_ai_mode_default="off")
    assert _call("concierge_intent", wa_on.id).calls == 1


def test_module_switched_features_are_never_blocked_here(db, rows):
    t = _tenant(db, ai_features={"call_analysis": False, "briefings": False})
    for task in ("marketing_content", "website_copy", "ask_haip_freeform_sql", "quick_classify"):
        assert _call(task, t.id).calls == 1


@pytest.mark.parametrize("task", ["call_analysis", "quick_classify", "marketing_content", "concierge_draft"])
def test_a_call_without_any_tenant_is_logged_and_blocked(db, rows, task):
    # No tenant_id argument and no llm_scope: nothing to check or charge it against, so no provider call and no row.
    inner = _Inner()
    with patch("app.services.ai_features.log") as log, pytest.raises(AIFeatureDisabled):
        asyncio.run(MeteredAdapter(inner, task, None).complete(system_prompt="s", user_message="u"))
    assert inner.calls == 0 and rows == []
    assert log.error.call_args.args[0] == "llm_call_without_tenant_blocked"


def test_the_prospect_assessment_write_up_is_the_one_task_allowed_without_a_tenant(db, rows):
    assert ai_features.PLATFORM_TASKS == {"assessment_narrative"}
    assert _call("assessment_narrative").calls == 1


# ── 3. read-only sources never get an AI reply ───────────────────────────────────────────────────────────


def _run_concierge(db, tid, conv, message_id, force=False):
    """The real concierge_draft task; get_llm returns a METERED fake so concierge_* usage rows are visible."""
    from app.workers.tasks.concierge_draft import concierge_draft

    inner = _Inner(
        reply={
            "tool_use": {
                "intent": "faq_answer",
                "reply": "Check-in is from 2 PM.",
                "confidence": 0.95,
                "citations": [],
                "needs_human": False,
            }
        }
    )
    with (
        patch("app.workers.tasks.concierge_draft.get_llm", lambda task, *a, **k: MeteredAdapter(inner, task, tid)),
        patch("app.workers.tasks.concierge_draft.SessionLocal", return_value=db),
        patch("app.services.push_service.send_to_tenant"),
        patch("app.services.leads_service.trigger_summary_refresh"),
        patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay") as wa_send,
    ):
        concierge_draft.run(message_id=message_id, conversation_id=conv.id, tenant_id=tid, force=force)
    return inner, wa_send


def _concierge_rows(rows):
    return [r for r in rows if str(r["meta"].get("task", "")).startswith("concierge_")]


def _outbound(db, conv):
    return db.query(Message).filter_by(conversation_id=conv.id, direction="outbound").count()


def test_an_official_whatsapp_thread_still_gets_a_draft(db, rows):
    t = _tenant(db)
    conv = _conv(db, t.id)
    inbound = _msg(db, t.id, conv)
    db.commit()
    inner, _ = _run_concierge(db, t.id, conv, inbound.id)
    assert (
        _outbound(db, conv) == 1 and inner.calls >= 1 and _concierge_rows(rows)
    )  # the harness sees rows when there are any


def test_a_personal_whatsapp_thread_gets_no_draft_and_no_concierge_usage(db, rows):
    t = _tenant(db, wa_ai_mode_default="autonomous")
    conv = _conv(db, t.id, source="personal_bridge")
    inbound = _msg(db, t.id, conv, channel_metadata={"source": "personal_bridge"})
    db.commit()
    inner, wa_send = _run_concierge(db, t.id, conv, inbound.id)
    assert _outbound(db, conv) == 0 and inner.calls == 0 and _concierge_rows(rows) == []
    wa_send.assert_not_called()


def test_a_personal_phone_message_in_an_official_thread_gets_no_draft(db, rows):
    # The guest also wrote to the official number, so the thread became official (whatsapp.py clears `source`); a message
    # they still send to the agent's personal phone lands in the same thread and must not be answered from the official number.
    t = _tenant(db, wa_ai_mode_default="autonomous")
    conv = _conv(db, t.id)
    inbound = _msg(db, t.id, conv, channel_metadata={"source": "personal_bridge"})
    db.commit()
    inner, wa_send = _run_concierge(db, t.id, conv, inbound.id)
    assert _outbound(db, conv) == 0 and inner.calls == 0 and _concierge_rows(rows) == []
    wa_send.assert_not_called()


@pytest.mark.parametrize("force", [False, True])
def test_a_lead_form_thread_gets_no_draft_and_no_concierge_usage(db, rows, force):
    # ai_mode left NULL on purpose: the refusal comes from the source and channel, not from the thread's "off" snapshot.
    t = _tenant(db, wa_ai_mode_default="autonomous", ig_ai_mode_default="autonomous")
    conv = _conv(db, t.id, channel=ChannelType.FACEBOOK, source="lead_form")
    inbound = _msg(db, t.id, conv, body="Filled the lead form", channel_metadata={"source": "lead_form"})
    db.commit()
    inner, _ = _run_concierge(db, t.id, conv, inbound.id if not force else str(uuid.uuid4()), force=force)
    assert _outbound(db, conv) == 0 and inner.calls == 0 and _concierge_rows(rows) == []


def test_can_send_is_false_for_every_read_only_source_and_channel():
    class C:
        def __init__(self, channel="whatsapp", source=None):
            self.channel, self.source, self.ai_mode = channel, source, None

    class M:
        def __init__(self, source):
            self.channel_metadata = {"source": source}

    assert ai_mode_service.can_send(C()) and ai_mode_service.can_send(C("instagram"))
    for source in ("personal_bridge", "lead_form", "chat_export"):
        assert not ai_mode_service.can_send(C(source=source))
        assert not ai_mode_service.can_send(C(), M(source))
    assert not ai_mode_service.can_send(C("facebook")) and not ai_mode_service.can_send(None)


def test_the_automation_draft_action_skips_a_lead_form_thread(db):
    from app.workers.tasks.automation_engine import _action_create_draft

    t = _tenant(db, wa_ai_mode_default="autonomous")
    conv = _conv(db, t.id, channel=ChannelType.FACEBOOK, source="lead_form")
    _msg(db, t.id, conv)
    db.commit()
    with patch("app.workers.tasks.concierge_draft.concierge_draft.apply_async") as queued:
        out = _action_create_draft(db, {}, {"conversation_id": conv.id}, t.id)
    queued.assert_not_called()
    assert out.startswith("skipped")


def test_the_automation_draft_action_still_queues_an_official_thread(db):
    from app.workers.tasks.automation_engine import _action_create_draft

    t = _tenant(db)
    conv = _conv(db, t.id)
    _msg(db, t.id, conv)
    db.commit()
    with patch("app.workers.tasks.concierge_draft.concierge_draft.apply_async") as queued:
        _action_create_draft(db, {}, {"conversation_id": conv.id}, t.id)
    queued.assert_called_once()


def _tid(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _headers(db, tid):
    from app.core.security import create_access_token, get_password_hash
    from app.models.user import User, UserRole

    u = User(
        id=str(uuid.uuid4()),
        tenant_id=tid,
        name="Owner",
        email=f"o-{uuid.uuid4().hex[:6]}@t.com",
        hashed_password=get_password_hash("pw"),
        role=UserRole.OWNER,
        is_active=True,
    )
    db.add(u)
    db.commit()
    return {"Authorization": f"Bearer {create_access_token({'sub': u.id, 'tenant_id': tid, 'role': 'owner'})}"}


@patch("app.api.v1.endpoints.conversations.concierge_draft.delay")
def test_the_write_a_draft_button_refuses_a_lead_form_thread(draft, client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    conv = _conv(db, tid, channel=ChannelType.FACEBOOK, source="lead_form")
    db.commit()
    res = client.post(f"/api/v1/conversations/{conv.id}/messages/ai-draft", json={}, headers=_headers(db, tid))
    assert res.status_code == 409 and res.json()["detail"]["code"] == "read_only_thread"
    draft.assert_not_called()


@patch("app.api.v1.endpoints.conversations.concierge_draft.delay")
def test_the_button_refuses_when_the_latest_message_went_to_a_personal_phone(draft, client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    conv = _conv(db, tid)
    _msg(db, tid, conv, channel_metadata={"source": "personal_bridge"})
    db.commit()
    res = client.post(f"/api/v1/conversations/{conv.id}/messages/ai-draft", json={}, headers=_headers(db, tid))
    assert res.status_code == 409
    draft.assert_not_called()


@patch("app.api.v1.endpoints.conversations.concierge_draft.delay")
def test_the_button_still_drafts_on_an_official_thread(draft, client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    conv = _conv(db, tid)
    _msg(db, tid, conv)
    db.commit()
    res = client.post(f"/api/v1/conversations/{conv.id}/messages/ai-draft", json={}, headers=_headers(db, tid))
    assert res.status_code == 200, res.text
    draft.assert_called_once()


def test_the_reply_safety_net_skips_a_lead_form_message(db):
    from app.workers.tasks import reply_recovery as rr

    t = _tenant(db)
    conv = _conv(db, t.id)
    _msg(db, t.id, conv, minutes=12, channel_metadata={"source": "lead_form"})
    db.commit()
    assert rr.missed_replies(db, t.id, datetime.now(UTC)) == []


def test_a_live_personal_whatsapp_message_queues_no_draft_and_no_summary_by_default(db):
    from app.services import whatsapp_personal_service as svc
    from tests.services.test_whatsapp_personal_service import _make_agent, _make_session

    t = _tenant(db)
    session = _make_session(db, t.id, _make_agent(db, t.id).id)
    with (
        patch("app.workers.tasks.concierge_draft.concierge_draft.apply_async") as drafted,
        patch("app.workers.tasks.concierge_draft.concierge_draft.delay") as drafted2,
        patch("app.services.whatsapp_personal_service.trigger_summary_refresh") as summary,
    ):
        msg = svc.ingest_chat_message(
            db,
            session,
            bridge_message_id=f"wm-{uuid.uuid4().hex}",
            from_phone="+919812345678",
            from_name="Priya",
            body="Hi, is the caravan free next weekend?",
        )
    assert msg is not None
    drafted.assert_not_called()
    drafted2.assert_not_called()
    summary.assert_not_called()  # "Personal WhatsApp: update lead summaries" defaults to off


def test_personal_whatsapp_summaries_run_once_switched_on(db):
    from app.services import whatsapp_personal_service as svc
    from tests.services.test_whatsapp_personal_service import _make_agent, _make_session

    t = _tenant(db, ai_features={"personal_whatsapp_summaries": True})
    session = _make_session(db, t.id, _make_agent(db, t.id).id)
    with patch("app.services.whatsapp_personal_service.trigger_summary_refresh") as summary:
        svc.ingest_chat_message(
            db,
            session,
            bridge_message_id=f"wm-{uuid.uuid4().hex}",
            from_phone="+919812345679",
            from_name="Anil",
            body="Hi, is the caravan free next weekend?",
        )
    summary.assert_called_once()


# ── 4. queue-time checks ─────────────────────────────────────────────────────────────────────────────────


def test_an_instagram_comment_follows_its_own_mode_which_defaults_to_off(db):
    t = _tenant(db, ig_ai_mode_default="shadow")
    conv = _conv(db, t.id, channel=ChannelType.INSTAGRAM)
    comment = _msg(db, t.id, conv, channel_metadata={"source": "comment"})
    dm = _msg(db, t.id, conv)
    db.commit()
    db.refresh(t)
    assert t.ig_comment_ai_mode_default == "off"
    assert ai_mode_service.resolve_mode(t, conv, comment) == "off"
    assert ai_mode_service.resolve_mode(t, conv, dm) == "shadow"
    t.ig_comment_ai_mode_default = "shadow"
    assert ai_mode_service.resolve_mode(t, conv, comment) == "shadow"


def test_the_kill_switch_never_turns_drafting_on_where_a_mode_is_off(db):
    t = _tenant(db, wa_ai_mode_default="off", ai_kill_switch=True)
    assert ai_mode_service.resolve_mode(t, _conv(db, t.id)) == "off"
    t.wa_ai_mode_default = "autonomous"
    assert ai_mode_service.resolve_mode(t, _conv(db, t.id)) == "shadow"


def test_lead_summaries_off_queues_no_summary_job(db):
    from app.services.leads_service import trigger_summary_refresh

    t = _tenant(db, ai_features={"lead_summaries": False})
    with (
        patch("app.workers.tasks.generate_ai_summary.generate_ai_summary.delay") as d,
        patch("app.workers.tasks.generate_ai_summary.generate_ai_summary.apply_async") as a,
    ):
        assert trigger_summary_refresh(db, str(uuid.uuid4()), t.id, source="manual") is False
        assert trigger_summary_refresh(db, str(uuid.uuid4()), t.id, source="message") is False
    d.assert_not_called()
    a.assert_not_called()


def test_call_analysis_off_stores_the_call_but_never_asks_the_model(db):
    from tests.workers import call_analysis_harness as h

    t = h.tenant(db)
    db.get(Tenant, t.id).ai_features = {"call_analysis": False}
    db.commit()
    c = h.call(db, t.id)
    llm = h.ScriptedLLM(tool_use={})
    h.run(db, t.id, c.id, llm)
    assert llm.calls == [] and db.get(Call, c.id).ai_score_status != "done"
