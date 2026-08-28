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
  call_analysis    → nvidia   nvidia/llama-3.3-nemotron-super-49b-v1.5
  call_scoring     → nvidia   nvidia/llama-3.3-nemotron-super-49b-v1.5
  ask_haip_rca     → nvidia   nvidia/nemotron-3-ultra-550b-a55b  (thinking=True)
  ask_haip_intent  → nvidia   meta/llama-3.1-8b-instruct
  quick_classify   → nvidia   meta/llama-3.1-8b-instruct
  bulk_batch       → nvidia   meta/llama-3.1-8b-instruct
  deep_reason      → nvidia   nvidia/nemotron-3-ultra-550b-a55b  (thinking=True)
  report_gen       → nvidia   nvidia/nemotron-3-ultra-550b-a55b
  concierge_draft  → gemini   gemini-3.6-flash
  ruflo_domain     → nvidia   nvidia/llama-3.3-nemotron-super-49b-v1.5
  ruflo_synthesis  → nvidia   nvidia/llama-3.3-nemotron-super-49b-v1.5
  fallback         → nvidia   mistralai/mistral-nemotron
                              (also where unknown task keys land)

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
    "call_analysis":   ("nvidia",  "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
    "call_scoring":    ("nvidia",  "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
    "ask_haip_rca":    ("nvidia",  "nvidia/nemotron-3-ultra-550b-a55b"),
    "ask_haip_intent": ("nvidia",  "meta/llama-3.1-8b-instruct"),
    "quick_classify":  ("nvidia",  "meta/llama-3.1-8b-instruct"),
    "bulk_batch":      ("nvidia",  "meta/llama-3.1-8b-instruct"),
    "deep_reason":     ("nvidia",  "nvidia/nemotron-3-ultra-550b-a55b"),
    "report_gen":      ("nvidia",  "nvidia/nemotron-3-ultra-550b-a55b"),
    "ruflo_domain":    ("nvidia",  "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
    "ruflo_synthesis": ("nvidia",  "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
    # Leads360 summary + structured analysis. Split off from concierge_draft
    # (guest-facing tone, now Gemini -- see below) because this is an
    # internal summary that should stay on NVIDIA regardless of what the
    # guest-facing task uses.
    "lead_summary":    ("nvidia",  "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
    # Ask HAIP free-form analyst: SQL generation needs real reasoning (same
    # tier as ask_haip_rca/deep_reason), summarizing already-fetched rows
    # into a narrative + chart spec is cheap classification-tier work.
    "ask_haip_freeform_sql":     ("nvidia", "nvidia/nemotron-3-ultra-550b-a55b"),
    "ask_haip_freeform_summary": ("nvidia", "meta/llama-3.1-8b-instruct"),
    # mistral-medium-3.5-128b reached end of life on 2026-08-07 and the
    # endpoint now returns HTTP 410, so this route was dead. mistral-nemotron
    # is the surviving mid-tier Mistral on NIM and was verified live.
    # Caveat: like the 8B, it answers tool-call prompts in prose rather than
    # emitting a tool call, so do not route structured-output work here --
    # the 49B/ultra models handle that.
    "fallback":        ("nvidia",  "mistralai/mistral-nemotron"),
    # HAIP Inbox prototype-wiring plan, ticket 3: rewrite an existing AI
    # draft in a new tone or language. Narrower/cheaper than a full
    # concierge_draft (no context gathering, no grounding), same cost tier
    # as quick_classify.
    "concierge_rewrite": ("nvidia", "meta/llama-3.1-8b-instruct"),
    # Moved NVIDIA -> Gemini (2026-08-25): NVIDIA's nemotron-49b was hanging
    # on certain prompts with no timeout and no exception (confirmed via a
    # direct 90s-ceiling call, no wrapper) -- a real, unresolved reliability
    # problem for guest-facing replies, not a cost/quality preference.
    #
    # gemini-2.5-flash-lite ("cheapest model", the original ask) was tried
    # first and rejected on real evidence, not a guess: run against the
    # actual concierge_reply.jinja prompt + CONCIERGE_TOOL schema, it
    # returned a truncated mid-sentence reply ("Hi Priya! We") with
    # confidence=0.9 -- comfortably over the 0.78 autonomous-send threshold,
    # meaning that garbage would have gone straight to a real guest.
    # gemini-2.5-flash itself then turned out to be blocked outright for
    # API keys tied to a newly-created GCP project ("This model models/
    # gemini-2.5-flash is no longer available to new users" -- Google's own
    # 404, confirmed live on the VPS's real key). gemini-3.6-flash is what
    # Google's error told this project to use, confirmed present in the
    # key's own /v1beta/models listing, and verified live against all 4
    # real prompt shapes (price/capacity/greeting/off-topic) -- complete,
    # correctly-grounded replies, no truncation, no price leaks.
    "concierge_draft": ("gemini",  "gemini-3.6-flash"),
    # Agent-attribution dashboard/reports: a short narrative on how one
    # agent handled guests over a period, synthesized from their own
    # scorecard numbers + call summaries + lead outcomes. Internal
    # (owner/agent report), not guest-facing -- same tier as lead_summary.
    "agent_performance_narrative": ("nvidia", "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
    # Detailed per-lead report: aggregate leads-summary + coaching feedback,
    # same tier as agent_performance_narrative (internal synthesis over
    # already-fetched structured data, not guest-facing).
    "agent_leads_feedback": ("nvidia", "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
    # Today (Worklist) AI Daily Briefing: one short narrative + flags
    # summarizing patterns across a tenant's *entire* current worklist
    # snapshot (repeated questions, missed-call time clusters). Internal
    # synthesis over already-fetched structured rows, same tier as
    # lead_summary/agent_performance_narrative -- not guest-facing.
    "daily_briefing": ("nvidia", "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
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

    # Unknown task keys previously defaulted to Claude. Production runs on
    # NVIDIA keys only with no ANTHROPIC_API_KEY provisioned (see the
    # concierge_draft note above), so any typo'd or newly-added task key
    # failed at runtime in prod while working locally for anyone with an
    # Anthropic key set. Defaulting to the fallback route keeps an unknown
    # task on the provider the deployment actually has credentials for.
    provider, model = _TASK_ROUTES.get(task) or _TASK_ROUTES["fallback"]
    if task not in _TASK_ROUTES:
        # stdlib logger in this module, not structlog -- structlog-style
        # kwargs here would raise TypeError instead of logging (the failure
        # mode CLAUDE.md documents for leads_service/identity_service).
        log.warning("llm_unknown_task_key: task=%s routed_to=%s", task, model)
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
    # `model` here is the task-routed model (from _TASK_ROUTES). It's bound
    # as each adapter's default_model so callers that don't pass model=
    # explicitly to .complete() still get the routed model, not whatever
    # hardcoded literal the adapter class happens to default to. Previously
    # this was silently discarded here -- every get_llm(task).complete(...)
    # call without an explicit model= kwarg used the adapter's own class
    # default regardless of the routing table, which is how ask_haip_rca /
    # deep_reason ended up silently running on llama-3.3-nemotron-super-49b
    # instead of the routed nemotron-3-ultra-550b-a55b thinking model.
    if provider == "nvidia":
        from app.adapters.llm.nvidia_nim import NvidiaNIMAdapter
        return NvidiaNIMAdapter(default_model=model) if model else NvidiaNIMAdapter()

    if provider == "claude":
        from app.adapters.llm.anthropic_claude import ClaudeAdapter
        return ClaudeAdapter(default_model=model) if model else ClaudeAdapter()

    if provider == "gemini":
        from app.adapters.llm.gemini import GeminiAdapter
        return GeminiAdapter(default_model=model) if model else GeminiAdapter()

    if provider == "openai":
        from app.adapters.llm.openai_gpt import OpenAIAdapter
        return OpenAIAdapter(default_model=model) if model else OpenAIAdapter()

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
