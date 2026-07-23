"""
OpenAI GPT adapter — implements LLMAdapter interface.

Used as fallback provider when Claude / Gemini are rate-limited.
Default model: gpt-4o-mini (fast, cheap, good quality).
"""

from __future__ import annotations
from typing import Optional
import logging

from app.adapters.llm.base import LLMAdapter
from app.core.config import settings

log = logging.getLogger(__name__)


class OpenAIAdapter(LLMAdapter):
    def __init__(self, api_key: str | None = None, default_model: str = "gpt-4o-mini"):
        self._api_key = api_key or settings.OPENAI_API_KEY
        self._default_model = default_model

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: Optional[str] = None,
        max_tokens: int = 1024,
        tools: Optional[list] = None,
    ) -> dict:
        model = model or self._default_model
        try:
            import openai
        except ImportError:
            raise RuntimeError(
                "openai package not installed. Run: pip install openai"
            )

        client = openai.AsyncOpenAI(api_key=self._api_key)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ]

        kwargs: dict = dict(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        resp = await client.chat.completions.create(**kwargs)
        choice = resp.choices[0]

        result: dict = {"content": "", "tool_use": None}

        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            tc = choice.message.tool_calls[0]
            import json
            result["tool_use"] = {
                "name":  tc.function.name,
                "input": json.loads(tc.function.arguments),
            }
        else:
            result["content"] = choice.message.content or ""

        return result
