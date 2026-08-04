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
    "nvidia/llama-3.3-nemotron-super-49b-v1.5":  "NVIDIA_API_KEY_MID",
    "meta/llama-3.1-8b-instruct":              "NVIDIA_API_KEY_FAST",
    "mistralai/mistral-medium-3.5-128b":       "NVIDIA_API_KEY_FALLBACK",
}


def _get_api_key(model: str) -> str:
    group_attr = _MODEL_KEY_GROUP.get(model, "NVIDIA_API_KEY")
    return getattr(settings, group_attr, "") or settings.NVIDIA_API_KEY


class NvidiaNIMAdapter(LLMAdapter):
    def __init__(self, api_key: str | None = None, default_model: str = "nvidia/llama-3.3-nemotron-super-49b-v1.5"):
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

        client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=_BASE_URL,
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

        log.debug(
            "nvidia_nim_complete",
            model=model,
            tokens_used=getattr(resp.usage, "total_tokens", None),
        )
        return result
