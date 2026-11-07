"""LLM_FORCE_PROVIDER=claude: every get_llm(task) runs on Claude first, the task's normal route as the fallback.

The Anthropic SDK is mocked throughout; no test makes a network call.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.llm import _TASK_ROUTES, get_llm
from app.adapters.llm.anthropic_claude import MODEL_HAIKU, MODEL_SONNET, ClaudeAdapter
from app.adapters.llm.fallback import FallbackAdapter


@pytest.fixture
def claude_on():
    with patch("app.core.config.settings.LLM_FORCE_PROVIDER", "claude"), \
         patch("app.core.config.settings.ANTHROPIC_API_KEY", "sk-ant-test-not-real"), \
         patch("anthropic.AsyncAnthropic") as sdk:
        yield sdk


def _reply(*blocks, stop="end_turn"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop,
                           usage=SimpleNamespace(input_tokens=1000, output_tokens=200,
                                                 cache_creation_input_tokens=0, cache_read_input_tokens=0))


def _tool(name, data):
    return SimpleNamespace(type="tool_use", name=name, input=data)


def test_flag_on_routes_an_nvidia_task_to_claude_with_the_normal_route_as_fallback(claude_on):
    adapter = get_llm("call_analysis").inner
    assert isinstance(adapter, FallbackAdapter)
    assert isinstance(adapter._primary, ClaudeAdapter) and adapter._primary._default_model == MODEL_SONNET
    assert adapter.provider == "claude"
    assert getattr(adapter._secondary, "provider", None) == "nvidia"
    assert adapter._primary_attempts == 1


def test_flag_on_routes_the_guest_reply_to_claude_with_gemini_as_fallback(claude_on):
    from app.adapters.llm.gemini import GeminiAdapter
    adapter = get_llm("concierge_draft").inner
    assert isinstance(adapter._primary, ClaudeAdapter) and adapter._primary._default_model == MODEL_SONNET
    assert isinstance(adapter._secondary, GeminiAdapter)
    assert adapter._primary_timeout == 30          # inside concierge_draft's 60 s outer bound for "claude"


def test_fast_tasks_use_haiku(claude_on):
    for task in ("quick_classify", "bulk_batch", "concierge_rewrite"):
        assert get_llm(task).inner._primary._default_model == MODEL_HAIKU


@pytest.mark.parametrize("task", list(_TASK_ROUTES.keys()))
def test_flag_on_covers_every_routed_task(claude_on, task):
    assert isinstance(get_llm(task).inner._primary, ClaudeAdapter)


def test_flag_off_is_unchanged():
    with patch("app.core.config.settings.LLM_FORCE_PROVIDER", ""), \
         patch("app.core.config.settings.ANTHROPIC_API_KEY", "sk-ant-test-not-real"):
        adapter = get_llm("concierge_draft").inner
    assert not isinstance(adapter, FallbackAdapter)
    assert adapter._default_model == _TASK_ROUTES["concierge_draft"][1]


def test_flag_without_a_key_is_unchanged():
    with patch("app.core.config.settings.LLM_FORCE_PROVIDER", "claude"), \
         patch("app.core.config.settings.ANTHROPIC_API_KEY", ""):
        adapter = get_llm("concierge_draft").inner
    assert not isinstance(adapter, FallbackAdapter)


@pytest.mark.asyncio
async def test_request_shape_is_valid_for_5_5_models(claude_on):
    from app.workers.tasks.concierge_draft import CONCIERGE_TOOL
    create = AsyncMock(return_value=_reply(_tool(CONCIERGE_TOOL["name"], {"reply": "Hi"})))
    claude_on.return_value.messages.create = create
    result = await get_llm("concierge_draft").complete(system_prompt="sys", user_message="Draft a reply for this guest.",
                                                       tools=[CONCIERGE_TOOL], max_tokens=600)
    sent = create.call_args.kwargs
    assert sent["tool_choice"] == {"type": "auto"}                       # forced tool choice is a 400 on 5.5
    assert not {"temperature", "top_p", "top_k", "thinking"} & set(sent)  # sampling removed; thinking adaptive by default
    assert [m["role"] for m in sent["messages"]] == ["user"]             # no assistant prefill
    assert sent["output_config"] == {"effort": "low"}
    assert sent["max_tokens"] == 600 + 4000                              # room for thinking
    assert "cache_control" not in sent["system"][0]                      # data-in-system prompt: no pointless cache write
    assert result["tool_use"] == {"reply": "Hi"} and result["model"] == MODEL_SONNET


@pytest.mark.asyncio
async def test_call_analysis_structured_output_parses_on_claude(claude_on):
    from app.workers.tasks.wrap_up import WRAP_UP_TOOL
    data = {"summary": "Guest asked about Coorg in May.", "disposition": "hot"}
    claude_on.return_value.messages.create = AsyncMock(return_value=_reply(
        SimpleNamespace(type="thinking", thinking=""), _tool(WRAP_UP_TOOL["name"], data)))
    result = await get_llm("call_analysis").complete(system_prompt="transcript...", user_message="Generate the wrap-up.",
                                                     tools=[WRAP_UP_TOOL])
    assert result["tool_use"] == data and "fallback_used" not in result


@pytest.mark.asyncio
async def test_constant_system_prompt_is_cached(claude_on):
    create = AsyncMock(return_value=_reply(SimpleNamespace(type="text", text="ok")))
    claude_on.return_value.messages.create = create
    await get_llm("analyst_brief").complete(system_prompt="rules", user_message="{" + "x" * 300 + "}")
    assert create.call_args.kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}


def _with_normal(adapter, answer):
    adapter.inner._secondary = MagicMock(provider="nvidia", complete=AsyncMock(return_value=answer))
    return adapter


@pytest.mark.asyncio
async def test_claude_error_falls_back_to_the_normal_route(claude_on):
    import anthropic
    claude_on.return_value.messages.create = AsyncMock(side_effect=anthropic.APIConnectionError(request=MagicMock()))
    adapter = _with_normal(get_llm("call_analysis"), {"content": "from nvidia", "tool_use": None})
    result = await adapter.complete(system_prompt="sys", user_message="hi")
    assert result["content"] == "from nvidia" and result["fallback_used"] is True


@pytest.mark.asyncio
async def test_a_reply_without_the_tool_call_falls_back(claude_on):
    from app.workers.tasks.wrap_up import WRAP_UP_TOOL
    claude_on.return_value.messages.create = AsyncMock(return_value=_reply(SimpleNamespace(type="text", text="prose")))
    adapter = _with_normal(get_llm("call_analysis"), {"content": "", "tool_use": {"summary": "nvidia"}})
    result = await adapter.complete(system_prompt="sys", user_message="hi", tools=[WRAP_UP_TOOL])
    assert result["tool_use"] == {"summary": "nvidia"} and result["fallback_used"] is True


@pytest.mark.asyncio
async def test_a_refusal_falls_back(claude_on):
    claude_on.return_value.messages.create = AsyncMock(return_value=_reply(stop="refusal"))
    adapter = _with_normal(get_llm("lead_summary"), {"content": "normal", "tool_use": None})
    assert (await adapter.complete(system_prompt="sys", user_message="hi"))["content"] == "normal"


def test_cost_uses_the_published_prices():
    from app.adapters.llm.anthropic_claude import cost_usd
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000,
             "cache_creation_input_tokens": 0}
    assert cost_usd(MODEL_SONNET, usage) == 12.10   # $2 in + $10 out + $0.10 cache read (0.05x input, pricing page 7 Nov 2026)
    assert cost_usd(MODEL_HAIKU, usage) == 0.61


def test_sonnet_cache_read_is_priced_at_0_05x_input():
    """Pricing page, 7 Nov 2026: Sonnet 5.5 cache hits are $0.10 / M (0.05x the $2 input), not $0.20."""
    from app.adapters.llm.anthropic_claude import MODEL_HAIKU, MODEL_SONNET, cost_usd
    usage = {"input_tokens": 1_000, "cache_read_input_tokens": 100_000, "output_tokens": 500}
    # 1,000 x $2 + 100,000 x $0.10 + 500 x $10, per million
    assert cost_usd(MODEL_SONNET, usage) == round((2_000 + 10_000 + 5_000) / 1_000_000, 6)
    assert cost_usd(MODEL_HAIKU, {"cache_read_input_tokens": 1_000_000}) == 0.01
