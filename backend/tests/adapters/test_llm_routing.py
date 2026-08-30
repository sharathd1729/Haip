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
    """Gemini migration (2026-08-25): concierge_draft moved off NVIDIA after
    nemotron-49b was confirmed to hang indefinitely (no timeout, no
    exception) on certain guest replies. Scoped to this task only -- every
    other task stays on NVIDIA (checked by the parametrized test above).
    gemini-3.6-flash, not flash-lite or 2.5-flash: a real test against the
    actual concierge prompt showed flash-lite truncating replies
    mid-sentence at confidence=0.9 (would auto-send over the 0.78
    threshold); 2.5-flash then turned out blocked outright for new-project
    API keys (Google's own 404, "no longer available to new users").
    3.6-flash is what Google's error pointed to, confirmed live."""
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
