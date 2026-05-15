"""
LLM adapter factory.

Provider priority (first match wins):
  1. Explicit `provider` argument passed to get_llm_adapter()
  2. LLM_PROVIDER env var
  3. Auto-detect: GEMINI_API_KEY set → gemini | ANTHROPIC_API_KEY set → claude
"""
from app.adapters.llm.base import LLMAdapter
from app.core.config import settings


def get_llm_adapter(provider: str | None = None) -> LLMAdapter:
    """
    Return the correct LLMAdapter.

    provider values: "gemini" | "claude"
    """
    chosen = (
        provider
        or settings.LLM_PROVIDER
        or _auto_detect_llm()
    )

    if chosen == "gemini":
        from app.adapters.llm.gemini import GeminiAdapter
        return GeminiAdapter()

    if chosen == "claude":
        from app.adapters.llm.anthropic_claude import ClaudeAdapter
        return ClaudeAdapter()

    raise ValueError(
        f"No LLM provider configured. "
        f"Set GEMINI_API_KEY (free) or ANTHROPIC_API_KEY in your .env"
    )


def _auto_detect_llm() -> str:
    if settings.GEMINI_API_KEY:
        return "gemini"
    if settings.ANTHROPIC_API_KEY:
        return "claude"
    return "gemini"   # will raise a clear error at runtime if key is missing


__all__ = ["get_llm_adapter", "LLMAdapter"]
