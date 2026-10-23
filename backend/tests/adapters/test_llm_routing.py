"""
get_llm(task) must actually route to the configured model -- regression
test for a bug where _build_adapter() computed the right (provider, model)
pair from _TASK_ROUTES but discarded `model` when constructing the
adapter, so every .complete() call without an explicit model= kwarg
silently used the adapter class's own hardcoded default instead of the
routed model. Discovered live: ask_haip_freeform_sql was routed to
nemotron-3-ultra-550b-a55b but every call actually ran on
llama-3.3-nemotron-super-49b-v1.5 (the NvidiaNIMAdapter class default).
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.adapters.llm import get_llm, _TASK_ROUTES


@pytest.mark.parametrize("task", list(_TASK_ROUTES.keys()))
def test_get_llm_binds_the_routed_model_as_default(task):
    provider, expected_model = _TASK_ROUTES[task]
    adapter = get_llm(task)
    assert adapter._default_model == expected_model, (
        f"get_llm({task!r}) routed to {expected_model!r} in _TASK_ROUTES "
        f"but the adapter's default_model is {adapter._default_model!r}"
    )


@pytest.mark.asyncio
async def test_complete_without_explicit_model_uses_the_routed_default():
    """End-to-end through the public get_llm() factory, not just checking
    the internal attribute -- confirms the routed model is what actually
    gets sent to the provider call when the caller omits model=."""
    with patch("app.core.config.settings.NVIDIA_API_KEY", "test-key"), \
         patch("openai.AsyncOpenAI") as mock_openai:
        mock_client = mock_openai.return_value
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock(finish_reason="stop", message=AsyncMock(content="ok", tool_calls=None))]
        mock_response.usage.total_tokens = 10
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        llm = get_llm("ask_haip_freeform_sql")
        await llm.complete(system_prompt="sys", user_message="hi", max_tokens=50)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "nvidia/nemotron-3-ultra-550b-a55b"


def test_concierge_draft_routes_to_gemini():
    """concierge_draft runs on Gemini (moved off NVIDIA 2026-08-25 after nemotron-49b hung on certain guest replies; detoured to
    NVIDIA 2026-09-27 to 2026-10-16 while the Google billing balance was negative). gemini-3.6-flash, not flash-lite (truncated
    replies at confidence 0.9) or 2.5-flash (blocked for new-project API keys). Every other task stays on NVIDIA."""
    from app.adapters.llm.gemini import GeminiAdapter

    adapter = get_llm("concierge_draft")
    assert isinstance(adapter, GeminiAdapter)
    assert adapter._default_model == "gemini-3.6-flash"


@pytest.mark.asyncio
async def test_explicit_model_kwarg_still_overrides_the_routed_default():
    """Callers that already pass model= explicitly (existing call sites)
    must keep working exactly as before -- this fix only changes behavior
    for calls that previously relied on an unintentional fallback."""
    with patch("app.core.config.settings.NVIDIA_API_KEY", "test-key"), \
         patch("openai.AsyncOpenAI") as mock_openai:
        mock_client = mock_openai.return_value
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock(finish_reason="stop", message=AsyncMock(content="ok", tool_calls=None))]
        mock_response.usage.total_tokens = 10
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        llm = get_llm("ask_haip_freeform_sql")
        await llm.complete(system_prompt="sys", user_message="hi", model="openai/gpt-oss-20b", max_tokens=50)

        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "openai/gpt-oss-20b"


def test_lead_stage_classify_routes_to_the_structured_output_tier(monkeypatch):
    """Lead autopilot's AI classifier (lead_autopilot_ai.py) returns JSON: gpt-oss-20b on NVIDIA, never the
    prose-only mistral-nemotron fallback, and it retries on Gemini when NVIDIA errors (when a Gemini key is set)."""
    from app.adapters.llm import _GEMINI_FALLBACK_TASKS
    from app.adapters.llm.fallback import FallbackAdapter
    from app.core.config import settings

    assert _TASK_ROUTES["lead_stage_classify"] == ("nvidia", "openai/gpt-oss-20b")
    assert _GEMINI_FALLBACK_TASKS["lead_stage_classify"] == 45
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    adapter = get_llm("lead_stage_classify")
    assert isinstance(adapter, FallbackAdapter) and adapter._default_model == "openai/gpt-oss-20b"


def test_outcome_reason_routes_to_the_structured_output_tier_with_gemini_fallback(monkeypatch):
    """Why a lead was won / lost (lead_outcome.py): JSON with verbatim quotes, gpt-oss-20b on NVIDIA + Gemini fallback."""
    from app.adapters.llm import _GEMINI_FALLBACK_TASKS
    from app.adapters.llm.fallback import FallbackAdapter
    from app.core.config import settings
    from app.core.prompt_versions import get_version

    assert _TASK_ROUTES["outcome_reason"] == ("nvidia", "openai/gpt-oss-20b")
    assert _GEMINI_FALLBACK_TASKS["outcome_reason"] == 45
    assert get_version("lead_outcome_reason") == "lead-outcome-reason-v1"
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    adapter = get_llm("outcome_reason")
    assert isinstance(adapter, FallbackAdapter) and adapter._default_model == "openai/gpt-oss-20b"
