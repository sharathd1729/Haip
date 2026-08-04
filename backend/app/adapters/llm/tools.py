"""Neutral tool-schema shape for LLM adapters (HAIP_AI_Autonomy_Plan.md
Phase 0, ticket 2).

The canonical `ToolSpec` shape is Anthropic's -- not an arbitrary new
format. It's already the de facto neutral shape in this codebase:
gemini.py's own `_anthropic_tool_to_gemini()` already treats it as the
input it converts from, and concierge_draft.py (Claude) already uses it
natively with zero translation. Only the OpenAI-compatible dialect (NVIDIA
NIM's endpoint, and OpenAIAdapter) actually needs a conversion step -- this
module is that one place, so it doesn't get reinvented per-adapter or,
worse, hand-copied into each task file.

Before this, wrap_up.py / classify.py / judge.py hand-wrote OpenAI-dialect
tool dicts directly, correct only because get_llm() happens to route all
three to NVIDIA today. The moment a grounded tool loop (Phase 1) needs the
same tool list to work against whichever provider a task is routed to --
including Claude -- that assumption breaks silently, per the plan's §0.2.
"""
from typing import TypedDict


class ToolSpec(TypedDict):
    name: str
    description: str
    input_schema: dict  # JSON Schema object: {type, properties, required}


def to_openai_tools(tools: list[ToolSpec]) -> list[dict]:
    """Canonical (Anthropic) shape -> OpenAI/NVIDIA function-calling shape."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
            },
        }
        for t in tools
    ]


def to_provider_tools(tools: list[ToolSpec], provider: str) -> list[dict]:
    """Render a neutral tool list into the dialect a given provider expects.
    Every LLMAdapter.complete() implementation calls this on its own
    `tools` argument before forwarding to its SDK -- callers everywhere
    else (task files) only ever declare tools once, in the canonical shape.

    provider: matches the provider strings in adapters/llm/__init__.py's
    _TASK_ROUTES ("nvidia" | "claude" | "gemini" | "openai").
    """
    if not tools:
        return []
    if provider in ("nvidia", "openai"):
        return to_openai_tools(tools)
    if provider in ("claude", "gemini"):
        # Already the canonical shape -- gemini.py does its own further
        # conversion internally (uppercased JSON-Schema types etc.), so
        # this stays a passthrough rather than duplicating that logic here.
        return list(tools)
    raise ValueError(f"to_provider_tools: unknown provider {provider!r}")
