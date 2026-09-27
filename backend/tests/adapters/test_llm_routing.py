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


def test_concierge_draft_routes_to_nvidia_emergency_reroute():
    """EMERGENCY, TEMPORARY (2026-09-27): concierge_draft was on Gemini
    (migrated 2026-08-25, after nemotron-49b was confirmed to hang
    indefinitely on certain guest replies) but Google billing went negative
    and started refusing every call, so guests got no real reply for hours.
    Rerouted to NVIDIA's openai/gpt-oss-20b -- not nemotron-49b, the model
    that made this task leave NVIDIA in the first place. Revert this test
    (and _TASK_ROUTES) back to gemini-3.6-flash once the GCP billing account
    shows a positive credit balance again."""
    from app.adapters.llm.nvidia_nim import NvidiaNIMAdapter

    adapter = get_llm("concierge_draft")
    assert isinstance(adapter, NvidiaNIMAdapter)
    assert adapter._default_model == "openai/gpt-oss-20b"


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
