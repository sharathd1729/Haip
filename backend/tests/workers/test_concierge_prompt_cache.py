"""AI cost card 3 (8 Nov 2026): the guest reply's cacheable layout and the calls it no longer makes.

- concierge_reply.jinja v21: the rules (system prompt, cached on Claude) are byte-identical for every guest of a workspace;
  the guest's data is the user message.
- The Claude adapter caches that system prompt even though the user message may be short (cache_system, per task).
- AI off / a closing "okay": no knowledge-base search (embedding call), no context build.
- Throwaway Instagram comments ("nice 😍"): no intent call, no draft; real ones are drafted after the burst debounce.
- The intent call's own route fits the 8 s grounding window, so its fallback can actually run.
No test calls a real model.
"""

import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.adapters.llm import _CLAUDE_TIMEOUTS, _GEMINI_FALLBACK_TASKS, _SINGLE_PRIMARY_ATTEMPT, _TASK_ROUTES, get_llm
from app.adapters.llm.anthropic_claude import ClaudeAdapter
from app.models.conversation import Message
from app.services.ig_keyword_match import is_throwaway_comment
from app.workers.tasks.concierge_draft import CONTEXT_MARKER, MAX_GROUNDING_SECONDS, split_prompt
from tests.workers.test_concierge_operational_data import CHECK_IN, CHECK_OUT, _conversation, _run, _tenant


class _Recorder:
    """get_llm stand-in that keeps the reply call's system prompt and user message apart."""

    def __init__(self, classification):
        self.classification, self.calls, self.intent_calls = classification, [], 0

    def __call__(self, task):
        outer = self

        class _LLM:
            provider = "scripted"

            async def complete(self, **kwargs):
                if task == "concierge_intent":
                    outer.intent_calls += 1
                    return {"tool_use": outer.classification}
                outer.calls.append((kwargs["system_prompt"], kwargs["user_message"]))
                return {
                    "tool_use": {
                        "reply": "The team will confirm.",
                        "confidence": 0.95,
                        "citations": [],
                        "needs_human": False,
                    }
                }

        return _LLM()


# ── the prompt layout ────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_rules_are_byte_identical_for_two_guests_of_one_workspace(db):
    t = _tenant(db, mode="shadow")
    _, conv_a, (msg_a,) = _conversation(db, t, f"Is the caravan free {CHECK_IN} to {CHECK_OUT} for 2 of us?")
    from app.models.guest import Guest

    other = Guest(id=str(uuid.uuid4()), tenant_id=t.id, phone=f"+9197{uuid.uuid4().int % 10**8:08d}", name="Arjun")
    _, conv_b, (msg_b,) = _conversation(db, t, "Do you allow pets? And is there parking?", guest=other)

    a = _Recorder({"intent": "availability_check", "check_in": CHECK_IN, "check_out": CHECK_OUT, "adults": 2})
    b = _Recorder({"intent": "faq_answer", "questions": ["do you allow pets", "is there parking"]})
    _run(db, t, conv_a, msg_a, a)
    _run(db, t, conv_b, msg_b, b, tone="brief")

    (sys_a, user_a), (sys_b, user_b) = a.calls[0], b.calls[0]
    assert sys_a == sys_b  # one cache entry serves every guest
    assert user_a != user_b
    assert "Priya" in user_a and "Arjun" in user_b  # the guest's data is the user message ...
    assert "Priya" not in sys_a and "Arjun" not in sys_a and CHECK_IN not in sys_a  # ... never the cached rules
    assert "UNDER 45 WORDS" in user_a and "UNDER 80 WORDS" in user_b and "maximally brief" in user_b
    assert CONTEXT_MARKER not in sys_a + user_a  # the marker never reaches the model
    assert "PRICING RULE" in sys_a and "NEVER INVENT A RULE" in sys_a and "Return STRICTLY this JSON" in sys_a
    assert len(sys_a) >= 2048  # above Sonnet/Haiku 5.5's 512-token minimum


def test_each_workspace_gets_its_own_rules(db):
    t1 = _tenant(db, mode="shadow", brand_name="Rathaa Caravans")
    t2 = _tenant(db, mode="shadow", brand_name="Jade Villas", price_disclosure="grounded")
    _, c1, (m1,) = _conversation(db, t1, "Hi")
    _, c2, (m2,) = _conversation(db, t2, "Hi")
    r1, r2 = _Recorder({"intent": "general"}), _Recorder({"intent": "general"})
    _run(db, t1, c1, m1, r1)
    _run(db, t2, c2, m2, r2)
    s1, s2 = r1.calls[0][0], r2.calls[0][0]
    assert "Rathaa Caravans" in s1 and "Jade Villas" not in s1
    assert "Jade Villas" in s2 and "Rathaa Caravans" not in s2
    assert (
        "CURRENT PRICING RULE" in s2 and "CURRENT PRICING RULE" not in s1
    )  # the tenant's price policy is part of its rules


def test_split_prompt_keeps_rules_and_data_apart():
    assert split_prompt("rules\n<<<CONCIERGE_CONTEXT>>>\ndata\n") == ("rules\n", "data\n")


# ── the adapter caches the system prompt ─────────────────────────────────────────────────────────────────────────────


def _reply(cache_read=0):
    return SimpleNamespace(
        content=[SimpleNamespace(type="tool_use", name="concierge_reply", input={"reply": "Hi"})],
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=900,
            output_tokens=60,
            cache_creation_input_tokens=0 if cache_read else 3000,
            cache_read_input_tokens=cache_read,
        ),
    )


@pytest.fixture
def claude_on():
    with (
        patch("app.core.config.settings.LLM_FORCE_PROVIDER", "claude"),
        patch("app.core.config.settings.ANTHROPIC_API_KEY", "sk-ant-test-not-real"),
        patch("anthropic.AsyncAnthropic") as sdk,
    ):
        yield sdk


@pytest.mark.asyncio
async def test_concierge_rules_are_cached_with_a_short_user_message_and_read_back(claude_on):
    from app.workers.tasks.concierge_draft import CONCIERGE_TOOL

    create = AsyncMock(side_effect=[_reply(), _reply(cache_read=3000)])
    claude_on.return_value.messages.create = create
    rules = "R" * 3000
    first = await get_llm("concierge_draft").complete(
        system_prompt=rules, user_message="GUEST CONTEXT\n- Name: A", tools=[CONCIERGE_TOOL]
    )
    second = await get_llm("concierge_draft").complete(
        system_prompt=rules, user_message="GUEST CONTEXT\n- Name: B", tools=[CONCIERGE_TOOL]
    )
    bodies = [c.kwargs for c in create.call_args_list]
    assert all(
        b["system"][0] == {"type": "text", "text": rules, "cache_control": {"type": "ephemeral"}} for b in bodies
    )
    assert bodies[0]["system"] == bodies[1]["system"]  # same prefix = a cache hit on the second call
    assert first["cache_creation_input_tokens"] == 3000 and second["cache_read_input_tokens"] == 3000


@pytest.mark.asyncio
async def test_other_tasks_and_short_rules_are_not_marked(claude_on):
    create = AsyncMock(return_value=_reply())
    claude_on.return_value.messages.create = create
    # call_analysis still carries the transcript in the system prompt: caching it would only add the write charge
    await get_llm("call_analysis").complete(system_prompt="T" * 5000, user_message="Generate the wrap-up.")
    assert "cache_control" not in create.call_args.kwargs["system"][0]
    await get_llm("concierge_draft").complete(system_prompt="short", user_message="hi")  # below the cacheable minimum
    assert "cache_control" not in create.call_args.kwargs["system"][0]


def test_only_the_concierge_reply_opts_in():
    assert ClaudeAdapter(cache_system=True)._cache_system and not ClaudeAdapter()._cache_system


# ── no context, no embedding when no reply will be written ───────────────────────────────────────────────────────────


def test_ai_off_builds_no_context_and_searches_no_knowledge(db):
    t = _tenant(db, mode="shadow")
    _, conv, (msg,) = _conversation(db, t, "Do you allow pets?")
    conv.ai_mode = "off"
    db.commit()
    llm = _Recorder({"intent": "general"})
    with (
        patch("app.workers.tasks.concierge_draft.build_concierge_context") as build,
        patch("app.services.knowledge_service.search_detailed") as search,
    ):
        drafts, _ = _run(db, t, conv, msg, llm)
    build.assert_not_called()
    search.assert_not_called()
    assert drafts == [] and llm.intent_calls == 0 and llm.calls == []


def test_a_closing_acknowledgement_builds_no_context(db):
    t = _tenant(db, mode="shadow")
    _, conv, (msg,) = _conversation(db, t, "okay thanks")
    with (
        patch("app.workers.tasks.concierge_draft._closing_acknowledgement", return_value=True),
        patch("app.workers.tasks.concierge_draft.build_concierge_context") as build,
    ):
        drafts, _ = _run(db, t, conv, msg, _Recorder({"intent": "general"}))
    build.assert_not_called()
    assert drafts == []


# ── Instagram comments ───────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", ["nice 😍", "😍🔥🔥", "wow amazing place", "@a_friend", "lovely!!"])
def test_throwaway_comments(text):
    assert is_throwaway_comment(text)


@pytest.mark.parametrize(
    "text",
    [
        "Price?",
        "how much for 2 nights",
        "available this weekend",
        "Is it pet friendly",
        "We want to book for 6 people next month",
    ],
)
def test_real_comments(text):
    assert not is_throwaway_comment(text)


def test_workspace_praise_words_extend_the_list():
    assert not is_throwaway_comment("mind blowing stuff here")
    assert is_throwaway_comment("mind blowing stuff here", "mind, blowing, stuff, here")


def _comment(db, text):
    from app.workers.tasks import process_instagram_comment as mod
    from tests.workers.test_process_instagram_comment_username import (
        _make_ig_integration,
        _make_tenant,
        _NoCloseSessionWrapper,
        _payload,
    )

    tenant = _make_tenant(db)
    _make_ig_integration(db, tenant.id)
    db.commit()
    with (
        patch.object(mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)),
        patch("app.workers.tasks.process_instagram_dm.backfill_instagram_guest_name"),
        patch("app.services.push_service.send_to_tenant"),
        patch("app.services.concierge_service.mark_pending_draft") as mark,
        patch("app.workers.tasks.concierge_draft.concierge_draft.apply_async") as queued,
        patch("app.workers.tasks.concierge_draft.get_llm") as llm,
    ):
        mod.process_instagram_comment.run({**_payload(), "text": text})
    msg = db.query(Message).filter_by(tenant_id=tenant.id).one()
    return msg, mark, queued, llm


def test_an_emoji_comment_makes_no_model_call(db):
    msg, mark, queued, llm = _comment(db, "nice 😍")
    queued.assert_not_called()
    llm.assert_not_called()
    assert msg.automation_outcome == "throwaway_comment"


def test_a_question_comment_is_drafted_after_the_burst_debounce(db):
    from app.services.concierge_service import DEBOUNCE_SECONDS

    msg, mark, queued, _ = _comment(db, "how much for 2 nights?")
    mark.assert_called_once()
    assert queued.call_args.kwargs["countdown"] == DEBOUNCE_SECONDS
    assert queued.call_args.kwargs["kwargs"]["message_id"] == msg.id


# ── the intent call fits the grounding window ────────────────────────────────────────────────────────────────────────


def test_intent_bounds_fit_the_grounding_window():
    assert _TASK_ROUTES["concierge_intent"] == _TASK_ROUTES["quick_classify"]
    assert "concierge_intent" in _SINGLE_PRIMARY_ATTEMPT
    assert _GEMINI_FALLBACK_TASKS["concierge_intent"] < MAX_GROUNDING_SECONDS  # the fallback gets time to answer
    assert _CLAUDE_TIMEOUTS["concierge_intent"] < MAX_GROUNDING_SECONDS


def test_intent_route_is_one_short_attempt_then_gemini():
    with (
        patch("app.core.config.settings.GEMINI_API_KEY", "g-test"),
        patch("app.core.config.settings.LLM_FORCE_PROVIDER", ""),
    ):
        inner = get_llm("concierge_intent").inner
    assert inner._primary_timeout == _GEMINI_FALLBACK_TASKS["concierge_intent"] and inner._primary_attempts == 1
    assert getattr(inner._secondary, "provider", None) == "gemini" or type(
        inner._secondary
    ).__name__.lower().startswith("gemini")


@pytest.mark.asyncio
async def test_the_extraction_uses_its_own_route():
    from app.workers.tasks import concierge_draft as cd

    seen = []

    def fake(task):
        seen.append(task)
        return MagicMock(complete=AsyncMock(return_value={"tool_use": {"intent": "general"}}))

    with patch.object(cd, "get_llm", fake):
        await cd._classify_and_extract("hi")
    assert seen == ["concierge_intent"]
