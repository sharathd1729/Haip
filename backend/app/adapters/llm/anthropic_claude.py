"""
Anthropic Claude adapter (anthropic SDK 0.125, Messages API).

Used when LLM_FORCE_PROVIDER=claude (adapters/llm/__init__.py), wrapped in FallbackAdapter so any failure here runs
the task's normal route. Claude 5.5 models think adaptively by default; depth is set with `output_config.effort`.
Valid request shape for 5.5: no assistant prefill, no temperature/top_p/top_k, no forced tool_choice (400 on
Sonnet 5.5) -- a tool is offered with tool_choice auto plus one instruction line, and a reply without the tool call
raises ClaudeNoToolCall so the fallback answers instead of a caller getting no structured output.
"""
from typing import Optional

import anthropic
import structlog

from app.adapters.llm.base import LLMAdapter
from app.adapters.llm.tools import to_provider_tools
from app.core.config import settings

log = structlog.get_logger()

MODEL_SONNET = "claude-sonnet-5-5"   # drafts, analysis, summaries, call QA, reports
MODEL_HAIKU = "claude-haiku-5-5"     # quick classify, bulk, rewrite

# USD per million tokens (input, output, cache read), from platform.claude.com/docs/en/about-claude/pricing on
# 7 Nov 2026: Sonnet 5.5 cache reads are 0.05x input ($0.10), not the usual 0.1x. A 5-minute cache write = 1.25x input.
# shortcut: Haiku 5.5 is priced for prompts up to 100K tokens ($0.50 / $2.50 beyond); HAIP prompts stay far below.
PRICES = {
    MODEL_SONNET: (2.00, 10.00, 0.10),
    MODEL_HAIKU: (0.10, 0.50, 0.01),
}

# Thinking tokens count against max_tokens; callers sized max_tokens for providers that do not think.
_THINKING_ROOM = 4000
_MAX_TOKENS_CEILING = 16000   # non-streaming requests stay well under the SDK's long-request limit

# The system prompt is cached only when the caller keeps its data in the user message (constant system text that
# repeats across calls). Templated prompts with guest data inside (concierge, wrap-up, judge) send a short instruction
# as the user message; caching those would only add the 1.25x write charge, never a read.
_CACHE_WHEN_USER_CHARS = 200


class ClaudeNoToolCall(Exception):
    """A tool was offered and Claude answered without calling it, or the reply was refused."""


def cost_usd(model: str, usage: dict) -> float:
    price_in, price_out, price_read = PRICES.get(model, PRICES[MODEL_SONNET])
    cost = (
        usage.get("input_tokens", 0) * price_in
        + usage.get("cache_creation_input_tokens", 0) * price_in * 1.25
        + usage.get("cache_read_input_tokens", 0) * price_read
        + usage.get("output_tokens", 0) * price_out
    )
    return round(cost / 1_000_000, 6)


class ClaudeAdapter(LLMAdapter):
    def __init__(self, default_model: str = MODEL_SONNET, effort: Optional[str] = None, timeout: float = 600.0):
        # Async client: complete() is awaited, and a sync call here would block the event loop.
        # max_retries=1: one quick retry on 429/5xx; anything slower is FallbackAdapter's job.
        self._client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY, max_retries=1, timeout=timeout)
        self._default_model = default_model
        self._effort = effort

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: Optional[str] = None,
        max_tokens: int = 2048,
        tools: Optional[list] = None,
        **_provider_specific,   # e.g. NVIDIA's thinking=...; not Claude parameters
    ) -> dict:
        model = model or self._default_model
        system_block = {"type": "text", "text": system_prompt}
        if len(user_message or "") >= _CACHE_WHEN_USER_CHARS:
            system_block["cache_control"] = {"type": "ephemeral"}
        system = [system_block]
        kwargs = dict(
            model=model,
            max_tokens=min(max_tokens + _THINKING_ROOM, _MAX_TOKENS_CEILING),
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        if getattr(self, "_effort", None):
            kwargs["output_config"] = {"effort": self._effort}
        if tools:
            kwargs["tools"] = to_provider_tools(tools, "claude")
            kwargs["tool_choice"] = {"type": "auto"}
            names = ", ".join(t["name"] for t in tools)
            system.append({"type": "text", "text": f"Give your answer by calling the {names} tool."})

        response = await self._client.messages.create(**kwargs)

        tool_result = None
        text_result = ""
        for block in response.content:
            if block.type == "tool_use":
                tool_result = block.input
            elif block.type == "text":
                text_result += block.text

        stop = getattr(response, "stop_reason", None)
        if stop == "refusal" or (tools and tool_result is None):
            raise ClaudeNoToolCall(f"stop_reason={stop}")

        u = response.usage
        usage = {
            "input_tokens": getattr(u, "input_tokens", 0) or 0,
            "output_tokens": getattr(u, "output_tokens", 0) or 0,
            "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
        }
        cost = cost_usd(model, usage)
        log.info("claude_call_completed", model=model, cost_usd=cost, **usage)
        return {
            "content": text_result,
            "tool_use": tool_result,
            **usage,
            "tokens_used": sum(usage.values()),
            "model": model,
        }
