"""Settings > AI: switch each AI feature on or off per workspace (docs/ai/AI_SWITCHES_SPEC.md). A feature that is off makes
no AI call at all.

Where each switch lives (one place each):
- reply modes: tenants.wa_ai_mode_default / ig_ai_mode_default / ig_comment_ai_mode_default (off | shadow | autonomous),
  resolved per reply by ai_mode_service.resolve_mode, which also refuses read-only threads (ai_mode_service.can_send);
- every other feature: tenants.ai_features JSON, {"call_analysis": false, ...}; a missing key = DEFAULTS.

Checked twice: before work is queued (`is_enabled` / `enabled`), and inside get_llm()'s MeteredAdapter (`check_task`),
which raises AIFeatureDisabled before any provider request and before any usage_events row. TASK_FEATURE must name every
task in adapters/llm._TASK_ROUTES (tests/test_ai_features.py fails otherwise); AI credits will charge against it later.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger()


class AIFeatureDisabled(Exception):
    """The workspace switched this AI feature off; no provider call was made. Callers log it and stop (no retry)."""

    def __init__(self, feature: str, task: str = ""):
        super().__init__(f"AI feature '{feature}' is switched off for this workspace (task {task})")
        self.feature = feature
        self.task = task


# Switchable features (tenants.ai_features) and their value when the workspace never set them.
DEFAULTS: dict[str, bool] = {
    "call_analysis": True,
    "call_transcription": True,
    "lead_summaries": True,
    "personal_whatsapp_summaries": False,  # a paid lead summary on every live personal-WhatsApp message
    "lead_autopilot": True,
    "briefings": True,
}

REPLIES = "replies"  # governed by the three reply-mode columns, not by ai_features
# No switch of their own here: Ask HAIP, Marketing Studio and Website follow their MODULE switch (workspace_modules,
# require_module), so a second on/off would be a second settings store; the rest is core plumbing.
UNSWITCHED = frozenset({"ask_haip", "marketing", "website", "operations", "personal_assistant", "core"})
# Work HAIP does for itself, where no workspace exists: the property-assessment write-up for HAIP's own prospects
# (PlatformLead). The only tasks allowed to run without a tenant; every other call without one is blocked.
PLATFORM_TASKS = frozenset({"assessment_narrative"})

_MARKETING = (
    "marketing_audit",
    "marketing_plan",
    "marketing_content",
    "marketing_content_premium",
    "marketing_research",
    "marketing_review",
    "marketing_brand_dna",
    "marketing_review_reply",
    "marketing_ota_copy",
    "marketing_tagging",
    "marketing_insights",
    "marketing_brief",
    "marketing_deck",
)

TASK_FEATURE: dict[str, str] = {
    "concierge_draft": REPLIES,
    "concierge_intent": REPLIES,
    "concierge_rewrite": REPLIES,
    "call_analysis": "call_analysis",
    "call_scoring": "call_analysis",
    "deep_reason": "call_analysis",
    "personal_call": "call_analysis",
    "lead_summary": "lead_summaries",
    "lead_stage_classify": "lead_autopilot",
    "outcome_reason": "lead_autopilot",
    "lead_followup_draft": "lead_autopilot",
    "agent_performance_narrative": "briefings",
    "agent_leads_feedback": "briefings",
    "analyst_brief": "briefings",
    "analyst_followup": "briefings",
    "chief_explain": "briefings",
    "ask_haip_freeform_sql": "ask_haip",
    "ask_haip_freeform_summary": "ask_haip",
    **dict.fromkeys(_MARKETING, "marketing"),
    "website_content": "website",
    "website_plan": "website",
    "website_copy": "website",
    "website_change": "website",
    "seo_brief": "website",
    "seo_outreach": "website",
    "assessment_narrative": "operations",
    "sop_generate": "operations",
    "staff_assistant": "operations",
    "personal_ask": "personal_assistant",
    "personal_digest": "personal_assistant",
    "personal_folder": "personal_assistant",
    "quick_classify": "core",
    "fallback": "core",
}

# Task names some callers pass that are not routed (they run on the "fallback" route).
_PREFIX_FEATURE = (("ask_haip_", "ask_haip"), ("marketing_", "marketing"), ("website_", "website"))

_CACHE_TTL = 60


def feature_for(task: str) -> str:
    if task in TASK_FEATURE:
        return TASK_FEATURE[task]
    for prefix, feature in _PREFIX_FEATURE:
        if task.startswith(prefix):
            return feature
    return "core"


def _reply_modes(tenant) -> list[str]:
    return [
        (getattr(tenant, col, None) or "shadow").lower()
        for col in ("wa_ai_mode_default", "ig_ai_mode_default", "ig_comment_ai_mode_default")
    ]


def _from_settings(features: dict | None, modes: list[str], feature: str) -> bool:
    if feature == REPLIES:
        return any(
            m != "off" for m in modes
        )  # backstop only; the real check is ai_mode_service.resolve_mode per thread
    if feature not in DEFAULTS:
        return True
    value = (features or {}).get(feature)
    return DEFAULTS[feature] if value is None else bool(value)


def is_enabled(tenant, feature: str) -> bool:
    """`tenant` is a Tenant row (None = defaults)."""
    if tenant is None:
        return _from_settings(None, ["shadow"], feature)
    return _from_settings(getattr(tenant, "ai_features", None), _reply_modes(tenant), feature)


def enabled(db, tenant_id: str, feature: str) -> bool:
    from app.models.tenant import Tenant

    return is_enabled(db.query(Tenant).filter_by(id=tenant_id).first(), feature)


def _cache_key(tenant_id: str) -> str:
    from app.core.cache import cache_key

    return cache_key("ai_features", tenant_id)


def _settings(tenant_id: str) -> tuple[dict | None, list[str]]:
    from app.core.cache import get_cached, set_cached

    cached = get_cached(_cache_key(tenant_id))
    if isinstance(cached, dict):
        return cached.get("features"), cached.get("modes") or ["shadow"]
    from app.core.database import SessionLocal
    from app.models.tenant import Tenant

    db = SessionLocal()
    try:
        t = db.query(Tenant).filter_by(id=tenant_id).first()
        features, modes = (getattr(t, "ai_features", None), _reply_modes(t)) if t else (None, ["shadow"])
    finally:
        db.close()
    set_cached(_cache_key(tenant_id), {"features": features, "modes": modes}, ttl=_CACHE_TTL)
    return features, modes


def forget(tenant_id: str) -> None:
    """Drop the cached switches after a change (the gate otherwise sees it within _CACHE_TTL seconds)."""
    from app.core.cache import _rdel

    _rdel(_cache_key(tenant_id))


def check_task(tenant_id: str | None, task: str) -> None:
    """The gate inside get_llm(): raises AIFeatureDisabled when `task`'s feature is off for this workspace. A call with no
    tenant (no tenant_id argument and no llm_scope) cannot be checked or charged, so it is logged and BLOCKED, except the
    PLATFORM_TASKS HAIP runs for itself."""
    if not tenant_id:
        if task in PLATFORM_TASKS:
            return
        log.error("llm_call_without_tenant_blocked", task=task)
        raise AIFeatureDisabled("no_tenant", task)
    feature = feature_for(task)
    if feature in UNSWITCHED:
        return
    try:
        features, modes = _settings(str(tenant_id))
    except Exception as exc:  # noqa: BLE001 -- a settings read failure must not stop the AI the workspace has on
        log.warning("ai_features_read_failed", tenant_id=tenant_id, error=str(exc)[:200])
        return
    if not _from_settings(features, modes, feature):
        log.info("ai_feature_disabled", tenant_id=tenant_id, feature=feature, task=task)
        raise AIFeatureDisabled(feature, task)
