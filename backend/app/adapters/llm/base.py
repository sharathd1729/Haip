from abc import ABC, abstractmethod
from typing import Any, Optional


class LLMAdapter(ABC):
    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 1024,
        tools: Optional[list] = None,
    ) -> dict:
        """Return dict with 'content' (str) and optional 'tool_use' (dict).

        `tools`, when given, must be a list of `adapters.llm.tools.ToolSpec`
        (the canonical/Anthropic shape: {name, description, input_schema}) --
        never a provider-specific dialect. Every implementation renders its
        own wire format internally via `adapters.llm.tools.to_provider_tools`
        before calling its SDK; callers declare tools exactly once."""
        ...
