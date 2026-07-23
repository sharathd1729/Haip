"""
Anthropic Claude adapter.
Wraps the SDK with structured tool-use output and prompt-cache prefix support.
"""
import anthropic
from typing import Optional
from app.adapters.llm.base import LLMAdapter
from app.core.config import settings
import structlog

log = structlog.get_logger()

# Model aliases matching the plan's conventions
MODEL_HAIKU = "claude-haiku-4-5-20251001"
MODEL_SONNET = "claude-sonnet-4-6"


class ClaudeAdapter(LLMAdapter):
    def __init__(self, default_model: str = MODEL_HAIKU):
        self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._default_model = default_model

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: Optional[str] = None,
        max_tokens: int = 2048,
        tools: Optional[list] = None,
    ) -> dict:
        model = model or self._default_model
        kwargs = dict(
            model=model,
            max_tokens=max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},  # prompt-cache prefix
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )
        if tools:
            kwargs["tools"] = tools

        try:
            response = self._client.messages.create(**kwargs)
        except Exception as e:
            log.error("claude_api_error", error=str(e), model=model)
            raise

        # Extract tool_use block if present
        tool_result = None
        text_result = ""
        for block in response.content:
            if block.type == "tool_use":
                tool_result = block.input
            elif block.type == "text":
                text_result += block.text

        # Rough cost logging
        usage = response.usage
        input_cost = (usage.input_tokens / 1_000_000) * (0.25 if "haiku" in model else 3.0)
        output_cost = (usage.output_tokens / 1_000_000) * (1.25 if "haiku" in model else 15.0)
        log.info(
            "claude_call_completed",
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_usd=round(input_cost + output_cost, 6),
        )

        return {
            "content": text_result,
            "tool_use": tool_result,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "model": model,
        }
