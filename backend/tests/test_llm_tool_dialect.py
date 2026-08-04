"""Tests for HAIP_AI_Autonomy_Plan.md Phase 0, ticket 2: normalizing the
LLM tool-schema dialect.

Before this, concierge_draft.py declared tools in Anthropic's shape while
wrap_up.py/classify.py/judge.py hand-wrote OpenAI/NVIDIA's shape directly --
correct only by coincidence, since get_llm() happened to route all three to
NVIDIA. Now every task file declares tools once in the canonical
(Anthropic) shape, and each adapter renders its own wire dialect via
adapters.llm.tools.to_provider_tools() before calling its SDK.
"""
import pytest

from app.adapters.llm.tools import ToolSpec, to_openai_tools, to_provider_tools
from app.workers.tasks.concierge_draft import CONCIERGE_TOOL
from app.workers.tasks.wrap_up import WRAP_UP_TOOL
from app.workers.tasks.classify import CLASSIFY_TOOL
from app.workers.tasks.judge import JUDGE_TOOL

_ALL_TASK_TOOLS = [CONCIERGE_TOOL, WRAP_UP_TOOL, CLASSIFY_TOOL, JUDGE_TOOL]


class TestCanonicalShapeConsistency:
    """The actual regression this ticket guards against: every task file's
    tool constant must be in the same (canonical) shape, not a mix of
    dialects that happens to work only because of today's routing table."""

    @pytest.mark.parametrize("tool", _ALL_TASK_TOOLS, ids=["concierge", "wrap_up", "classify", "judge"])
    def test_every_task_tool_is_canonical_shape(self, tool):
        assert set(tool.keys()) == {"name", "description", "input_schema"}
        assert isinstance(tool["name"], str) and tool["name"]
        assert isinstance(tool["input_schema"], dict)
        assert tool["input_schema"]["type"] == "object"
        assert "properties" in tool["input_schema"]

    @pytest.mark.parametrize("tool", _ALL_TASK_TOOLS, ids=["concierge", "wrap_up", "classify", "judge"])
    def test_no_task_tool_still_has_openai_wrapper(self, tool):
        """Regression guard for exactly the bug this ticket fixes."""
        assert "type" not in tool  # not {"type": "function", ...}
        assert "function" not in tool
        assert "parameters" not in tool  # OpenAI calls it parameters, not input_schema


class TestToOpenAiTools:
    def test_renders_openai_function_wrapper(self):
        tools: list[ToolSpec] = [{
            "name": "check_availability",
            "description": "Check property availability",
            "input_schema": {"type": "object", "properties": {"from": {"type": "string"}}, "required": ["from"]},
        }]
        rendered = to_openai_tools(tools)
        assert rendered == [{
            "type": "function",
            "function": {
                "name": "check_availability",
                "description": "Check property availability",
                "parameters": {"type": "object", "properties": {"from": {"type": "string"}}, "required": ["from"]},
            },
        }]

    def test_missing_input_schema_defaults_to_empty_object(self):
        rendered = to_openai_tools([{"name": "x", "description": "d"}])
        assert rendered[0]["function"]["parameters"] == {"type": "object", "properties": {}}

    def test_real_task_tools_render_without_error(self):
        for tool in _ALL_TASK_TOOLS:
            rendered = to_openai_tools([tool])
            assert rendered[0]["type"] == "function"
            assert rendered[0]["function"]["name"] == tool["name"]
            assert rendered[0]["function"]["parameters"] == tool["input_schema"]


class TestToProviderTools:
    def test_empty_or_none_returns_empty_list(self):
        assert to_provider_tools([], "claude") == []
        assert to_provider_tools(None, "nvidia") == []

    def test_claude_is_passthrough(self):
        tools = [CONCIERGE_TOOL]
        assert to_provider_tools(tools, "claude") == tools

    def test_gemini_is_passthrough(self):
        """gemini.py does its own further conversion internally -- this
        layer only needs to hand it the canonical shape unchanged."""
        tools = [CONCIERGE_TOOL]
        assert to_provider_tools(tools, "gemini") == tools

    def test_nvidia_renders_openai_dialect(self):
        rendered = to_provider_tools([CLASSIFY_TOOL], "nvidia")
        assert rendered[0]["type"] == "function"
        assert rendered[0]["function"]["name"] == "classify_call"

    def test_openai_renders_openai_dialect(self):
        rendered = to_provider_tools([JUDGE_TOOL], "openai")
        assert rendered[0]["type"] == "function"
        assert rendered[0]["function"]["name"] == "judge_call"

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError):
            to_provider_tools([CONCIERGE_TOOL], "cohere")


class TestAdapterWiring:
    """Confirm the adapters actually call to_provider_tools with their own
    provider name -- not just that the helper function works in isolation."""

    @pytest.mark.asyncio
    async def test_claude_adapter_sends_canonical_shape_to_sdk(self, monkeypatch):
        from app.adapters.llm.anthropic_claude import ClaudeAdapter
        from unittest.mock import MagicMock

        adapter = ClaudeAdapter.__new__(ClaudeAdapter)  # skip __init__ (no API key needed)
        adapter._default_model = "claude-haiku-4-5-20251001"

        captured = {}

        class _FakeContent:
            type = "text"
            text = "ok"

        class _FakeUsage:
            input_tokens = 10
            output_tokens = 5

        class _FakeResponse:
            content = [_FakeContent()]
            usage = _FakeUsage()

        class _FakeMessages:
            def create(self, **kwargs):
                captured.update(kwargs)
                return _FakeResponse()

        class _FakeClient:
            messages = _FakeMessages()

        adapter._client = _FakeClient()

        await adapter.complete(
            system_prompt="sys", user_message="hi", tools=[CONCIERGE_TOOL],
        )

        assert captured["tools"] == [CONCIERGE_TOOL]  # passthrough, already canonical

    @pytest.mark.asyncio
    async def test_nvidia_adapter_sends_openai_shape_to_sdk(self, monkeypatch):
        from app.adapters.llm import nvidia_nim

        adapter = nvidia_nim.NvidiaNIMAdapter(api_key="fake-key-for-test")

        captured = {}

        class _FakeMessage:
            tool_calls = None
            content = "ok"

        class _FakeChoice:
            finish_reason = "stop"
            message = _FakeMessage()

        class _FakeUsage:
            total_tokens = 15

        class _FakeResponse:
            choices = [_FakeChoice()]
            usage = _FakeUsage()

        class _FakeCompletions:
            async def create(self, **kwargs):
                captured.update(kwargs)
                return _FakeResponse()

        class _FakeChat:
            completions = _FakeCompletions()

        class _FakeAsyncOpenAI:
            def __init__(self, **kwargs):
                pass
            chat = _FakeChat()

        import openai as openai_module
        monkeypatch.setattr(openai_module, "AsyncOpenAI", _FakeAsyncOpenAI)

        await adapter.complete(
            system_prompt="sys", user_message="hi", tools=[CLASSIFY_TOOL],
        )

        assert captured["tools"][0]["type"] == "function"
        assert captured["tools"][0]["function"]["name"] == "classify_call"
        assert captured["tools"][0]["function"]["parameters"] == CLASSIFY_TOOL["input_schema"]
