"""
NVIDIA NIM adapter — OpenAI-compatible endpoint.

Base URL: https://integrate.api.nvidia.com/v1
One NVIDIA_API_KEY covers all models: Nemotron, Llama, Mistral, DeepSeek, etc.

Thinking mode: nemotron-3-ultra-550b-a55b supports extended reasoning.
Pass thinking=True to enable it (used for deep_reason and ask_haip_rca tasks).
"""

from __future__ import annotations

import json
import structlog
from typing import Optional

from app.adapters.llm.base import LLMAdapter
from app.adapters.llm.tools import to_provider_tools
from app.core.config import settings

log = structlog.get_logger()

_BASE_URL = "https://integrate.api.nvidia.com/v1"

# Models that support thinking/reasoning mode
_THINKING_MODELS = frozenset({
    "nvidia/nemotron-3-ultra-550b-a55b",
})

# Map model → settings key for per-group rate-limit isolation.
# Falls back to NVIDIA_API_KEY if group key is empty.
_MODEL_KEY_GROUP: dict[str, str] = {
    "nvidia/nemotron-3-ultra-550b-a55b":       "NVIDIA_API_KEY_HEAVY",
    # nvidia/llama-3.3-nemotron-super-49b-v1.5 and meta/llama-3.1-8b-instruct
    # both reached NIM end-of-life 2026-08-26 (HTTP 410). Tried
    # openai/gpt-oss-120b (100s+ latency, occasional 504s) then
    # deepseek-v4-flash-0731 (fast at first, ~46s) for the mid tier, but
    # deepseek-v4-flash went into a sustained outage 2026-08-30 -- 6 of 7
    # real calls 504'd over 30 minutes, even a trivial 10-token prompt
    # timed out at 90s. openai/gpt-oss-20b is now the _TASK_ROUTES model
    # for BOTH the small and mid tiers -- it's been 100% reliable all day,
    # so this is a real capability step-down for the more complex mid-tier
    # tasks, accepted as the emergency fallback until NIM's congestion
    # clears. Both tiers share this one rate-limit isolation group now.
    "openai/gpt-oss-20b":                      "NVIDIA_API_KEY_FAST",
    "mistralai/mistral-medium-3.5-128b":       "NVIDIA_API_KEY_FALLBACK",
}


def _get_api_key(model: str) -> str:
    group_attr = _MODEL_KEY_GROUP.get(model, "NVIDIA_API_KEY")
    return getattr(settings, group_attr, "") or settings.NVIDIA_API_KEY


class NvidiaNIMAdapter(LLMAdapter):
    def __init__(self, api_key: str | None = None, default_model: str = "openai/gpt-oss-20b"):
        self._api_key_override = api_key  # explicit override (e.g. tests)
        self._default_model = default_model

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: Optional[str] = None,
        max_tokens: int = 4096,
        tools: Optional[list] = None,
        thinking: bool = False,
    ) -> dict:
        model = model or self._default_model
        api_key = self._api_key_override or _get_api_key(model)
        if not api_key:
            raise RuntimeError(
                "No NVIDIA API key set. "
                "Set NVIDIA_API_KEY (global) or NVIDIA_API_KEY_HEAVY/MID/FAST/FALLBACK in .env. "
                "Get keys at https://build.nvidia.com"
            )

        try:
            import openai
        except ImportError:
            raise RuntimeError("openai package not installed. Run: pip install openai")

        # max_retries=0: the SDK's own default (2) silently retries a
        # failed/slow request internally before ever raising back to the
        # caller -- invisible to any timeout or logging wrapped around this
        # call. Confirmed live: concierge_draft.py's own 2-attempt retry
        # loop (added after real timeouts) logged near-identical elapsed
        # times across separate task runs, which is what you'd expect from
        # a deterministic internal retry/backoff schedule hitting the same
        # failure repeatedly within the outer wait_for window, not
        # necessarily one request truly hanging. Callers that want retries
        # own that decision explicitly now (concierge_draft.py does), so
        # this must not also be retrying underneath them.
        client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=_BASE_URL,
            max_retries=0,
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ]

        kwargs: dict = dict(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.2,
            top_p=0.7,
        )

        # Enable thinking mode for supported models when requested
        if thinking and model in _THINKING_MODELS:
            kwargs["extra_body"] = {
                "chat_template_kwargs": {"enable_thinking": True},
                "reasoning_budget": min(max_tokens, 8192),
            }
            kwargs["temperature"] = 1.0   # required for thinking mode
            kwargs["top_p"] = 0.95

        if tools:
            kwargs["tools"] = to_provider_tools(tools, "nvidia")
            kwargs["tool_choice"] = "auto"

        resp = await client.chat.completions.create(**kwargs)
        choice = resp.choices[0]

        result: dict = {"content": "", "tool_use": None}

        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            tc = choice.message.tool_calls[0]
            # Flat dict — matches anthropic_claude.py's tool_use shape
            # (tool_result = block.input) that every caller expects. This used
            # to wrap it in {"name":..., "input":...} instead, so every caller's
            # judge_result.get("criterion_scores")/wu.get("summary")/etc always
            # silently hit their default (score 0.0, summary never written).
            result["tool_use"] = json.loads(tc.function.arguments)
        else:
            result["content"] = choice.message.content or ""

        usage = getattr(resp, "usage", None)
        result["model"] = model
        if usage is not None:
            # Reported to callers (the concierge logs it) so cost and runaway prompts can be seen per provider.
            result["input_tokens"] = getattr(usage, "prompt_tokens", None)
            result["output_tokens"] = getattr(usage, "completion_tokens", None)
            result["tokens_used"] = getattr(usage, "total_tokens", None)
        log.debug(
            "nvidia_nim_complete",
            model=model,
            tokens_used=getattr(usage, "total_tokens", None),
        )
        return result
