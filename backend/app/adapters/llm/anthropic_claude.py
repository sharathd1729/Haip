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

# USD per million tokens (input, output, cache read), Claude API pricing (8 Nov 2026): cache reads = 0.1x input
# (Sonnet 5.5 $0.20; the 7 Nov table had $0.10). A 5-minute cache write = 1.25x input (CACHE_WRITE_MULTIPLIER; HAIP only
# sends 5-minute ephemeral breakpoints). Message Batches = half of every line (BATCH_DISCOUNT).
# shortcut: Haiku 5.5 is priced for prompts up to 100K tokens ($0.50 / $2.50 beyond); HAIP prompts stay far below.
PRICES = {
    MODEL_SONNET: (2.00, 10.00, 0.20),
    MODEL_HAIKU: (0.10, 0.50, 0.01),
}
CACHE_WRITE_MULTIPLIER = 1.25
BATCH_DISCOUNT = 0.5

# Thinking tokens count against max_tokens; callers sized max_tokens for providers that do not think.
_THINKING_ROOM = 4000
_MAX_TOKENS_CEILING = 16000   # non-streaming requests stay well under the SDK's long-request limit

# The system prompt is cached when it is constant text that repeats across calls: either the caller keeps its data in
# the user message (a long user message), or the task's prompt is laid out that way and says so (cache_system, set per
# task in adapters/llm/__init__.py: concierge_draft's rules are the system prompt, the guest's data the user message,
# whatever its length). Templated prompts with data inside the system prompt (wrap-up, judge, classify) send a short
# instruction as the user message; caching those would only add the 1.25x write charge, never a read.
_CACHE_WHEN_USER_CHARS = 200
# Sonnet / Haiku 5.5 cache a prefix of 512+ tokens (~4 chars a token); a shorter one is never written, so no marker.
_MIN_CACHE_SYSTEM_CHARS = 2048


class ClaudeNoToolCall(Exception):
    """A tool was offered and Claude answered without calling it, or the reply was refused."""


def cost_usd(model: str, usage: dict, batch: bool = False) -> float:
    price_in, price_out, price_read = PRICES.get(model, PRICES[MODEL_SONNET])
    cost = (
        (usage.get("input_tokens") or 0) * price_in
        + (usage.get("cache_creation_input_tokens") or 0) * price_in * CACHE_WRITE_MULTIPLIER
        + (usage.get("cache_read_input_tokens") or 0) * price_read
        + (usage.get("output_tokens") or 0) * price_out
    )
    return round(cost * (BATCH_DISCOUNT if batch else 1.0) / 1_000_000, 6)


def build_params(system_prompt: str, user_message: str, model: str, max_tokens: int, tools: Optional[list],
                 effort: Optional[str], cache_system: bool = False) -> dict:
    """The Messages API request body. Shared by complete() and the Message Batches path (adapters/llm/batch.py)."""
    system_block = {"type": "text", "text": system_prompt}
    if len(user_message or "") >= _CACHE_WHEN_USER_CHARS or (
            cache_system and len(system_prompt or "") >= _MIN_CACHE_SYSTEM_CHARS):
        system_block["cache_control"] = {"type": "ephemeral"}
    system = [system_block]
    params = dict(
        model=model,
        max_tokens=min(max_tokens + _THINKING_ROOM, _MAX_TOKENS_CEILING),
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    if effort:
        params["output_config"] = {"effort": effort}
    if tools:
        params["tools"] = to_provider_tools(tools, "claude")
        params["tool_choice"] = {"type": "auto"}
        names = ", ".join(t["name"] for t in tools)
        system.append({"type": "text", "text": f"Give your answer by calling the {names} tool."})
    return params


def usage_of(response) -> dict:
    u = getattr(response, "usage", None)
    return {
        "input_tokens": getattr(u, "input_tokens", 0) or 0,
        "output_tokens": getattr(u, "output_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
    }


def parse_response(response, model: str, tools_given: bool) -> dict:
    """The adapter result dict from a Message (a live reply or a batch result). Raises ClaudeNoToolCall."""
    tool_result = None
    text_result = ""
    for block in response.content:
        if block.type == "tool_use":
            tool_result = block.input
        elif block.type == "text":
            text_result += block.text
    stop = getattr(response, "stop_reason", None)
    if stop == "refusal" or (tools_given and tool_result is None):
        raise ClaudeNoToolCall(f"stop_reason={stop}")
    usage = usage_of(response)
    return {"content": text_result, "tool_use": tool_result, **usage, "tokens_used": sum(usage.values()), "model": model}


class ClaudeAdapter(LLMAdapter):
    def __init__(self, default_model: str = MODEL_SONNET, effort: Optional[str] = None, timeout: float = 600.0,
                 cache_system: bool = False):
        # Async client: complete() is awaited, and a sync call here would block the event loop.
        # max_retries=1: one quick retry on 429/5xx; anything slower is FallbackAdapter's job.
        self._client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY, max_retries=1, timeout=timeout)
        self._default_model = default_model
        self._effort = effort
        self._cache_system = cache_system

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
        params = build_params(system_prompt, user_message, model, max_tokens, tools, getattr(self, "_effort", None),
                              cache_system=getattr(self, "_cache_system", False))
        from app.adapters.llm.metered import attempt
        rec = attempt("claude", model)
        response = await self._client.messages.create(**params)
        usage = usage_of(response)
        rec.update(usage)   # recorded before the no-tool-call check: a reply without the tool is still billed
        result = parse_response(response, model, bool(tools))
        log.info("claude_call_completed", model=model, cost_usd=cost_usd(model, usage), **usage)
        return result
