"""
LLM adapter factory with task-based routing.

Usage:
  # Task-based routing (preferred — no vendor lock-in):
  from app.adapters.llm import get_llm
  adapter = get_llm("call_analysis")      # → Nemotron 70B (or Claude if key present)
  adapter = get_llm("quick_classify")     # → Llama 3.1 8B

  # Direct provider (legacy / override):
  from app.adapters.llm import get_llm_adapter
  adapter = get_llm_adapter("nvidia")

Routing rules:
  call_analysis    → nvidia   nvidia/llama-3.1-nemotron-70b-instruct
  call_scoring     → nvidia   nvidia/llama-3.3-nemotron-super-49b-v1
  ask_haip_rca     → nvidia   nvidia/nemotron-3-ultra-550b-a55b  (thinking=True)
  ask_haip_intent  → nvidia   meta/llama-3.1-8b-instruct
  quick_classify   → nvidia   meta/llama-3.1-8b-instruct
  bulk_batch       → nvidia   meta/llama-3.1-8b-instruct
  deep_reason      → nvidia   nvidia/nemotron-3-ultra-550b-a55b  (thinking=True)
  report_gen       → nvidia   nvidia/nemotron-3-ultra-550b-a55b
  concierge_draft  → claude   claude-haiku-4-5   (kept — Indian hospitality tone)
  ruflo_domain     → nvidia   nvidia/llama-3.1-nemotron-70b-instruct
  ruflo_synthesis  → nvidia   nvidia/llama-3.1-nemotron-70b-instruct
  fallback         → nvidia   mistralai/mistral-medium-3.5-128b

Provider priority for get_llm_adapter (legacy path):
  1. Explicit `provider` argument
  2. LLM_PROVIDER env var
  3. Auto-detect: NVIDIA_API_KEY → nvidia | ANTHROPIC_API_KEY → claude | GEMINI_API_KEY → gemini
"""

from __future__ import annotations
import logging
from typing import Optional

from app.adapters.llm.base import LLMAdapter
from app.core.config import settings

log = logging.getLogger(__name__)


# ─── Task routing table ───────────────────────────────────────────────────────

# (provider, model)
_TASK_ROUTES: dict[str, tuple[str, str]] = {
    # ── NVIDIA NIM (primary) ──────────────────────────────────────────────────
    "call_analysis":   ("nvidia",  "nvidia/llama-3.1-nemotron-70b-instruct"),
    "call_scoring":    ("nvidia",  "nvidia/llama-3.3-nemotron-super-49b-v1"),
    "ask_haip_rca":    ("nvidia",  "nvidia/nemotron-3-ultra-550b-a55b"),
    "ask_haip_intent": ("nvidia",  "meta/llama-3.1-8b-instruct"),
    "quick_classify":  ("nvidia",  "meta/llama-3.1-8b-instruct"),
    "bulk_batch":      ("nvidia",  "meta/llama-3.1-8b-instruct"),
    "deep_reason":     ("nvidia",  "nvidia/nemotron-3-ultra-550b-a55b"),
    "report_gen":      ("nvidia",  "nvidia/nemotron-3-ultra-550b-a55b"),
    "ruflo_domain":    ("nvidia",  "nvidia/llama-3.1-nemotron-70b-instruct"),
    "ruflo_synthesis": ("nvidia",  "nvidia/llama-3.1-nemotron-70b-instruct"),
    "fallback":        ("nvidia",  "mistralai/mistral-medium-3.5-128b"),
    # ── Claude kept for tone-sensitive tasks ──────────────────────────────────
    "concierge_draft": ("claude",  "claude-haiku-4-5"),
}


def get_llm(task: str, tenant_id: Optional[str] = None) -> LLMAdapter:
    """
    Return the correct LLMAdapter for a given task.

    task values: call_analysis | call_scoring | ask_haip_rca | ask_haip_intent |
                 quick_classify | bulk_batch | deep_reason | report_gen |
                 concierge_draft | ruflo_domain | ruflo_synthesis | fallback

    tenant_id: when provided, checks tenant.llm_provider_override to allow
               enterprise tenants to pin all AI to one provider.
    """
    # Tenant-level provider override (enterprise feature)
    if tenant_id:
        override = _tenant_provider_override(tenant_id)
        if override:
            return _build_adapter(override, model=None)

    provider, model = _TASK_ROUTES.get(task, ("claude", "claude-sonnet-4-6"))
    return _build_adapter(provider, model)


def get_llm_adapter(provider: Optional[str] = None) -> LLMAdapter:
    """
    Legacy / direct provider path.
    Prefer get_llm(task) for new code.
    """
    chosen = provider or settings.LLM_PROVIDER or _auto_detect_llm()
    return _build_adapter(chosen, model=None)


# ─── Internals ───────────────────────────────────────────────────────────────

def _build_adapter(provider: str, model: Optional[str]) -> LLMAdapter:
    if provider == "nvidia":
        from app.adapters.llm.nvidia_nim import NvidiaNIMAdapter
        return NvidiaNIMAdapter()

    if provider == "claude":
        from app.adapters.llm.anthropic_claude import ClaudeAdapter
        return ClaudeAdapter()

    if provider == "gemini":
        from app.adapters.llm.gemini import GeminiAdapter
        return GeminiAdapter()

    if provider == "openai":
        from app.adapters.llm.openai_gpt import OpenAIAdapter
        return OpenAIAdapter()

    raise ValueError(
        f"Unknown LLM provider: {provider!r}. "
        f"Valid values: nvidia | claude | gemini | openai"
    )


def _auto_detect_llm() -> str:
    if settings.NVIDIA_API_KEY:
        return "nvidia"
    if settings.ANTHROPIC_API_KEY:
        return "claude"
    if settings.GEMINI_API_KEY:
        return "gemini"
    return "nvidia"   # will fail at runtime with a clear API-key error


def _tenant_provider_override(tenant_id: str) -> Optional[str]:
    """
    Check if the tenant has pinned a specific LLM provider.
    Returns provider string or None.
    Cached per request — does not hit DB on every call.
    """
    try:
        from app.core.cache import get_cached, set_cached, cache_key
        ck = cache_key("tenant_llm_override", tenant_id)
        cached = get_cached(ck)
        if cached is not None:
            return cached or None     # empty string stored as "no override"

        from app.core.database import SessionLocal
        from app.models.tenant import Tenant
        db = SessionLocal()
        try:
            t = db.query(Tenant).filter_by(id=tenant_id).first()
            override = getattr(t, "llm_provider_override", None) if t else None
            set_cached(ck, override or "", ttl=300)
            return override
        finally:
            db.close()
    except Exception as exc:
        log.debug("tenant_llm_override_skip: %s", exc)
        return None


__all__ = ["get_llm", "get_llm_adapter", "LLMAdapter"]
