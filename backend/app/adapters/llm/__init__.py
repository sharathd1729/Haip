"""
LLM adapter factory with task-based routing.

Usage:
  # Task-based routing (preferred — no vendor lock-in):
  from app.adapters.llm import get_llm
  adapter = get_llm("call_analysis")      # → gpt-oss-20b
  adapter = get_llm("quick_classify")     # → gpt-oss-20b

  # Direct provider (legacy / override):
  from app.adapters.llm import get_llm_adapter
  adapter = get_llm_adapter("nvidia")

Routing rules:
  call_analysis    → nvidia   openai/gpt-oss-20b
  call_scoring     → nvidia   openai/gpt-oss-20b
  ask_haip_rca     → nvidia   nvidia/nemotron-3-ultra-550b-a55b  (thinking=True)
  ask_haip_intent  → nvidia   openai/gpt-oss-20b
  quick_classify   → nvidia   openai/gpt-oss-20b
  bulk_batch       → nvidia   openai/gpt-oss-20b
  deep_reason      → nvidia   nvidia/nemotron-3-ultra-550b-a55b  (thinking=True)
  report_gen       → nvidia   nvidia/nemotron-3-ultra-550b-a55b
  concierge_draft  → gemini   gemini-3.6-flash
  lead_stage_classify → nvidia openai/gpt-oss-20b  (lead autopilot)
  ruflo_domain     → nvidia   openai/gpt-oss-20b
  ruflo_synthesis  → nvidia   openai/gpt-oss-20b
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
    # nvidia/llama-3.3-nemotron-super-49b-v1.5 reached NVIDIA NIM
    # end-of-life on 2026-08-26 alongside meta/llama-3.1-8b-instruct
    # (confirmed live: HTTP 410 Gone, took out judge.py and
    # generate_ai_summary.py in prod). Tried openai/gpt-oss-120b first
    # (correct tool calls, good quality, but ran close to NIM's gateway
    # timeout ceiling -- 100s+ even on tiny prompts, occasional 504s),
    # then deepseek-ai/deepseek-v4-flash-0731 (faster, ~46s, zero 504s
    # at first) -- but confirmed live 2026-08-30 that deepseek-v4-flash
    # went into a sustained outage: 6 of 7 real generate_ai_summary calls
    # 504'd over 30 minutes straight, and even a trivial 10-token "say hi"
    # timed out completely at 90s. openai/gpt-oss-20b (the small-tier
    # model, already proven 100% reliable all day) is the emergency
    # fallback here too -- a real capability step-down for these more
    # complex internal-analysis tasks, but working beats not responding.
    # Revisit deepseek-v4-flash/gpt-oss-120b once NIM's congestion clears.
    "call_analysis":   ("nvidia",  "openai/gpt-oss-20b"),
    "call_scoring":    ("nvidia",  "openai/gpt-oss-20b"),
    "ask_haip_rca":    ("nvidia",  "nvidia/nemotron-3-ultra-550b-a55b"),
    # meta/llama-3.1-8b-instruct reached NVIDIA NIM end-of-life on
    # 2026-08-26 (confirmed live: HTTP 410 Gone, took out classify.py's
    # quick_classify calls in prod). openai/gpt-oss-20b is a real,
    # currently-live NIM model (confirmed in /v1/models) verified live
    # against this exact tool-call shape -- correct classify_intent tool
    # call, no prose fallback, no cold-start lag. Same NVIDIA key, same
    # provider branch, just a model-string swap.
    "ask_haip_intent": ("nvidia",  "openai/gpt-oss-20b"),
    "quick_classify":  ("nvidia",  "openai/gpt-oss-20b"),
    "bulk_batch":      ("nvidia",  "openai/gpt-oss-20b"),
    "deep_reason":     ("nvidia",  "nvidia/nemotron-3-ultra-550b-a55b"),
    "report_gen":      ("nvidia",  "nvidia/nemotron-3-ultra-550b-a55b"),
    "ruflo_domain":    ("nvidia",  "openai/gpt-oss-20b"),
    "ruflo_synthesis": ("nvidia",  "openai/gpt-oss-20b"),
    # Leads360 summary + structured analysis. Split off from concierge_draft
    # (guest-facing tone, now Gemini -- see below) because this is an
    # internal summary that should stay on NVIDIA regardless of what the
    # guest-facing task uses.
    "lead_summary":    ("nvidia",  "openai/gpt-oss-20b"),
    # Ask HAIP free-form analyst: SQL generation needs real reasoning (same
    # tier as ask_haip_rca/deep_reason), summarizing already-fetched rows
    # into a narrative + chart spec is cheap classification-tier work.
    "ask_haip_freeform_sql":     ("nvidia", "nvidia/nemotron-3-ultra-550b-a55b"),
    "ask_haip_freeform_summary": ("nvidia", "openai/gpt-oss-20b"),
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
    "concierge_rewrite": ("nvidia", "openai/gpt-oss-20b"),
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
    # Back on Gemini (2026-10-16) after a 2026-09-27 emergency detour to NVIDIA gpt-oss-20b: the Gemini billing account had gone
    # negative and Google refused every call ("credit balance above $0 required"), so guests got only the holding reply.
    # The owner topped the account up. If Google starts refusing again (billing, quota), reroute to ("nvidia",
    # "openai/gpt-oss-20b") and see concierge_draft.py's per-provider timeout + safe holding-reply fallback.
    "concierge_draft": ("gemini",  "gemini-3.6-flash"),
    # Agent-attribution dashboard/reports: a short narrative on how one
    # agent handled guests over a period, synthesized from their own
    # scorecard numbers + call summaries + lead outcomes. Internal
    # (owner/agent report), not guest-facing -- same tier as lead_summary.
    "agent_performance_narrative": ("nvidia", "openai/gpt-oss-20b"),
    # Detailed per-lead report: aggregate leads-summary + coaching feedback,
    # same tier as agent_performance_narrative (internal synthesis over
    # already-fetched structured data, not guest-facing).
    "agent_leads_feedback": ("nvidia", "openai/gpt-oss-20b"),
    # Today (Worklist) AI Daily Briefing: one short narrative + flags
    # summarizing patterns across a tenant's *entire* current worklist
    # snapshot (repeated questions, missed-call time clusters). Internal
    # synthesis over already-fetched structured rows, same tier as
    # lead_summary/agent_performance_narrative -- not guest-facing.
    "daily_briefing": ("nvidia", "openai/gpt-oss-20b"),
    # Lead autopilot (lead_autopilot_ai.py): reads one lead's recent messages + call notes and returns a stage decision
    # (lost | qualified | booked | none) with confidence and evidence quotes. Internal classification over already-fetched
    # rows, structured JSON output -- the gpt-oss-20b tier, never mistral-nemotron (answers tool prompts in prose).
    "lead_stage_classify": ("nvidia", "openai/gpt-oss-20b"),
    # Public property assessment (HAIP's own website): a short write-up that may only restate numbers the engine
    # already computed (assessment_narrative.py rejects any other number). Not guest-facing, same tier as the above.
    "assessment_narrative": ("nvidia", "openai/gpt-oss-20b"),
    # Lead follow-up draft (lead_followup_draft.py, lead workflows P5/P6 in "drafts" mode): one short WhatsApp follow-up a
    # PERSON approves before it is sent; a price in the reply is rejected and replaced by fixed wording. Same tier as
    # concierge_rewrite (short text, no tools), with the Gemini fallback below.
    "lead_followup_draft": ("nvidia", "openai/gpt-oss-20b"),
    # Why a lead was won / lost (lead_outcome.py): reads the lead's own call transcripts + messages and returns one reason
    # from the fixed catalogue with verbatim quotes (checked in code). Internal analysis, structured JSON output -- the
    # gpt-oss-20b tier with the Gemini fallback below. A PERSON confirms it; it never sets the reason by itself.
    "outcome_reason": ("nvidia", "openai/gpt-oss-20b"),
    # AI business analyst (services/analyst/brief.py): a structured brief from computed facts (JSON). Internal, not
    # guest-facing; every number is re-checked against the facts and a deterministic brief stands in on any failure.
    "analyst_brief": ("nvidia", "openai/gpt-oss-20b"),
    # "Ask a follow-up" on a report (services/analyst/ask.py): a short answer over a trimmed copy of the same facts. Its own
    # route (it used ask_haip_freeform_summary, which has no Gemini fallback and timed out in production at 60 s); the Ask
    # HAIP summary route stays without one because it reads raw query rows.
    "analyst_followup": ("nvidia", "openai/gpt-oss-20b"),
    # Marketing Studio: every step runs on Gemini (24 Oct 2026). On gpt-oss-20b the studio's tool calls came back empty
    # (reasoning used the whole output budget; live: brand voice, finish_reason MAX_TOKENS, 0 output tokens), and the
    # owner chose Gemini for these steps. Structured output via one tool; every result is re-validated and reviewed by
    # a person before anything leaves HAIP. Budgets in marketing_ai_service.MAX_TOKENS leave room for thinking.
    "marketing_audit":   ("gemini", "gemini-3.6-flash"),
    "marketing_plan":    ("gemini", "gemini-3.6-flash"),
    "marketing_content": ("gemini", "gemini-3.6-flash"),
    # Agency M3: the owner may pick the stronger writer for copy. Falls back to marketing_content on any error.
    "marketing_content_premium": ("gemini", "gemini-3.6-flash"),
    "marketing_research": ("gemini", "gemini-3.6-flash"),
    "marketing_review":   ("gemini", "gemini-3.6-flash"),     # brand editor: advisory findings on one draft
    "marketing_brand_dna": ("gemini", "gemini-3.6-flash"),    # brand voice DRAFT from the business's own published text
    "marketing_review_reply": ("gemini", "gemini-3.6-flash"), # a reply to a public Google review; a person posts it
    "marketing_ota_copy": ("gemini", "gemini-3.6-flash"),     # OTA listing copy drafts (agency M7); a person pastes them
    # Studio plan phase 1: tags each post / ad from its text (marketing_tagging), and explains the weekly Insights
    # report whose numbers code computed (marketing_insights_report; a sentence with an unknown number is dropped).
    "marketing_tagging":  ("gemini", "gemini-3.6-flash"),
    "marketing_insights": ("gemini", "gemini-3.6-flash"),
    # Studio plan phase 3: shoot & collab brief (creative text over the radar's evidence) and the monthly deck's prose
    # over code-computed facts (numbers grounded like the analyst's).
    "marketing_brief": ("gemini", "gemini-3.6-flash"),
    "marketing_deck":  ("gemini", "gemini-3.6-flash"),
    # Website builder AI developer (website_ai_service): structured JSON operations on the site draft via one tool,
    # every operation re-validated against website_blocks.json; never publishes. Same tool-calling tier as marketing_*.
    "website_content": ("nvidia", "openai/gpt-oss-20b"),
    # Website art director (website_builder_ai, W2): sitemap / wireframe / 3 style directions as one tool call each,
    # validated as a SiteSpec. Planning = the studio's Gemini tier; a one-slot copy polish is a small task on Flash-Lite.
    "website_plan": ("gemini", "gemini-3.6-flash"),
    "website_copy": ("gemini", "gemini-3.1-flash-lite"),
}


# Internal-analysis tasks that retry on Gemini when NVIDIA errors or exceeds the
# given seconds (NIM has had multi-hour 504/hang stretches -- calls sat at
# "pending", Leads360 summaries went missing). Value = how long the NVIDIA
# attempt may run before Gemini is tried. Needs GEMINI_API_KEY; without it the
# task simply runs on NVIDIA as before. Guest-facing tasks are not listed:
# concierge_draft is already on Gemini and has its own retry/timeout handling.
_GEMINI_FALLBACK_TASKS: dict[str, float] = {
    "call_analysis":               60,
    "call_scoring":                60,
    "lead_summary":                60,
    "daily_briefing":              60,
    "quick_classify":              30,
    "lead_stage_classify":         45,
    "agent_performance_narrative": 60,
    "agent_leads_feedback":        60,
    "deep_reason":                 120,   # judge's low-confidence re-score
    "assessment_narrative":        60,
    "lead_followup_draft":         40,
    "outcome_reason":              45,
    "analyst_brief":               90,
    "analyst_followup":            40,
    "website_content":             90,
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
    adapter = _build_adapter(provider, model)

    primary_timeout = _GEMINI_FALLBACK_TASKS.get(task)
    if primary_timeout is not None and provider == "nvidia" and settings.GEMINI_API_KEY:
        from app.adapters.llm.fallback import FallbackAdapter
        adapter = FallbackAdapter(
            primary=adapter,
            secondary=_build_adapter("gemini", None),
            task=task,
            primary_timeout=primary_timeout,
        )
    return adapter


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
        adapter = NvidiaNIMAdapter(default_model=model) if model else NvidiaNIMAdapter()

    elif provider == "claude":
        from app.adapters.llm.anthropic_claude import ClaudeAdapter
        adapter = ClaudeAdapter(default_model=model) if model else ClaudeAdapter()

    elif provider == "gemini":
        from app.adapters.llm.gemini import GeminiAdapter
        adapter = GeminiAdapter(default_model=model) if model else GeminiAdapter()

    elif provider == "openai":
        from app.adapters.llm.openai_gpt import OpenAIAdapter
        adapter = OpenAIAdapter(default_model=model) if model else OpenAIAdapter()

    else:
        raise ValueError(
            f"Unknown LLM provider: {provider!r}. "
            f"Valid values: nvidia | claude | gemini | openai"
        )

    # Duck-typed, not on the LLMAdapter ABC -- lets callers pick
    # provider-specific behavior (e.g. concierge_draft.py's per-provider
    # reply timeout) without re-deriving the provider from _TASK_ROUTES
    # themselves, which would silently go stale against a tenant override.
    adapter.provider = provider
    return adapter


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
