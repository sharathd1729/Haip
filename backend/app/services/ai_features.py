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
# Their usage_events rows go to this internal workspace (migration 218), module INTERNAL_MODULE, so the cost is visible.
INTERNAL_TENANT_ID = "haip-internal"
INTERNAL_MODULE = "haip_internal"

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
    "call_transcription": "call_transcription",  # speech-to-text rows (kind transcription_call), not an LLM route
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


# ── Settings > AI view and changes (GET / PATCH /api/v1/settings/ai) ─────────────────────────────────────────────────

VIEW_DAYS = 30
MODES = ("off", "shadow", "autonomous")
# Reply rows -> the tenant column that holds the mode (the one place each mode lives).
REPLY_MODES = {
    "whatsapp_replies": "wa_ai_mode_default",
    "instagram_dm_replies": "ig_ai_mode_default",
    "instagram_comment_replies": "ig_comment_ai_mode_default",
}
# Confidence floor for automatic replies (ai_mode_service.resolve_threshold): comments share the Instagram column.
REPLY_THRESHOLDS = {
    "whatsapp_replies": "wa_ai_confidence_threshold",
    "instagram_dm_replies": "ig_ai_confidence_threshold",
}
# Switches whose cost cannot be shown on their own row.
NO_OWN_COST = {
    "personal_whatsapp_summaries": "in_lead_summaries",  # the same lead_summary task
}


def _bucket() -> dict:
    return {"cost_usd": 0.0, "uses": 0, "cost_unknown_uses": 0}


def _add(bucket: dict, meta: dict) -> None:
    bucket["uses"] += 1
    cost = meta.get("cost_usd")
    if cost is None:
        bucket["cost_unknown_uses"] += 1  # never estimated (llm_usage_report's rule)
    else:
        bucket["cost_usd"] += float(cost)


def _reply_row(channel, meta) -> str:
    raw = str(getattr(channel, "value", channel) or "").lower()
    if raw == "whatsapp":
        return "whatsapp_replies"
    if raw == "instagram":
        source = meta.get("source") if isinstance(meta, dict) else None
        return "instagram_comment_replies" if source == "comment" else "instagram_dm_replies"
    return "replies_other"


def usage_by_feature(db, tenant_id: str, days: int = VIEW_DAYS, now=None) -> dict:
    """{feature or reply row: {cost_usd, uses, cost_unknown_uses}} over the last `days` days from usage_events (the kinds
    llm_usage_report counts). Reply calls are split by the channel of the guest message they answered (ref_type
    "message"); one with no such message (the "write a draft" button, rewrites) goes to "replies_other"."""
    from collections import defaultdict
    from datetime import UTC, datetime, timedelta

    from app.models.conversation import Message
    from app.models.usage_event import UsageEvent
    from app.services.llm_usage_report import KINDS

    since = (now or datetime.now(UTC)) - timedelta(days=days)
    out: dict = defaultdict(_bucket)
    reply_calls: dict[str, list[dict]] = defaultdict(list)
    for meta, ref_type, ref_id in db.query(UsageEvent.meta, UsageEvent.ref_type, UsageEvent.ref_id).filter(
        UsageEvent.tenant_id == tenant_id,
        UsageEvent.kind.in_((*KINDS, "transcription_call")),
        UsageEvent.created_at >= since,
    ):
        meta = meta or {}
        feature = feature_for(str(meta.get("task") or ""))
        if feature != REPLIES:
            _add(out[feature], meta)
        elif ref_type == "message" and ref_id:
            reply_calls[ref_id].append(meta)
        else:
            _add(out["replies_other"], meta)
    ids = list(reply_calls)
    for i in range(0, len(ids), 500):  # SQLite caps bound parameters
        for mid, channel, mmeta in db.query(Message.id, Message.channel, Message.channel_metadata).filter(
            Message.tenant_id == tenant_id, Message.id.in_(ids[i : i + 500])
        ):
            for meta in reply_calls.pop(mid):
                _add(out[_reply_row(channel, mmeta)], meta)
    for metas in reply_calls.values():  # the message is gone or never existed (the button's fresh id)
        for meta in metas:
            _add(out["replies_other"], meta)
    for b in out.values():
        b["cost_usd"] = round(b["cost_usd"], 4)
    return dict(out)


def unused_drafts(db, tenant_id: str, days: int = VIEW_DAYS, now=None) -> dict:
    """{reply row: drafts that expired with nobody acting on them} (ai_draft_outcomes, outcome "expired"). By the draft's
    channel and what it answered: concierge drafts record channel_metadata["answers"] = "comment" | "message"; older drafts
    without it count on the Instagram DM row."""
    from datetime import UTC, datetime, timedelta

    from app.models.ai_draft_outcome import AIDraftOutcome
    from app.models.conversation import Message

    since = (now or datetime.now(UTC)) - timedelta(days=days)
    rows = (
        db.query(Message.channel, Message.channel_metadata)
        .join(AIDraftOutcome, AIDraftOutcome.draft_message_id == Message.id)
        .filter(
            AIDraftOutcome.tenant_id == tenant_id,
            AIDraftOutcome.outcome == "expired",
            AIDraftOutcome.created_at >= since,
        )
    )
    out: dict[str, int] = {}
    for channel, meta in rows:
        answered = "comment" if isinstance(meta, dict) and meta.get("answers") == "comment" else None
        key = _reply_row(channel, {"source": answered})
        out[key] = out.get(key, 0) + 1
    return out


def view(db, tenant, now=None) -> dict:
    """Everything Settings > AI shows: each switch, its value and its last-30-day cost and uses."""
    usage = usage_by_feature(db, tenant.id, VIEW_DAYS, now)
    unused = unused_drafts(db, tenant.id, VIEW_DAYS, now)
    empty = _bucket()
    features = []
    for key, default in DEFAULTS.items():
        row = {"key": key, "enabled": is_enabled(tenant, key), "default": default}
        if key in NO_OWN_COST:
            row.update(cost_usd=None, uses=None, cost_unknown_uses=None, cost_note=NO_OWN_COST[key])
        else:
            row.update(usage.get(key, empty))
        features.append(row)
    from app.services.llm_usage_report import DEFAULT_USD_INR

    return {
        "period_days": VIEW_DAYS,
        "usd_inr": DEFAULT_USD_INR,  # providers bill in US$; the screen shows rupees at this rate
        "reply_modes": [
            {
                "key": key,
                "mode": (getattr(tenant, col, None) or "shadow").lower(),
                "choices": list(MODES),
                # automatic replies below this confidence are held as drafts; comments use the Instagram DM value
                "threshold": float(
                    getattr(tenant, REPLY_THRESHOLDS.get(key, "ig_ai_confidence_threshold"), None) or 0.78
                ),
                "threshold_editable": key in REPLY_THRESHOLDS,
                **usage.get(key, empty),
                "unused_drafts": unused.get(key, 0),
            }
            for key, col in REPLY_MODES.items()
        ],
        "replies_other": usage.get("replies_other", empty),
        "features": features,
        "module_switched": [{"key": key, **usage.get(key, empty)} for key in sorted(UNSWITCHED)],
        "total_cost_usd": round(sum(b["cost_usd"] for b in usage.values()), 4),
    }


def apply(
    db, tenant, actor_user_id: str, features: dict, reply_modes: dict, thresholds: dict | None = None
) -> list[dict]:
    """Change switches; one audit row (`ai.feature_changed`, old -> new) per real change. The caller commits and then calls
    forget(tenant.id). Keys and values are validated by schemas/ai_settings.py."""
    from app.core.audit import append_audit

    changes: list[dict] = []
    stored = dict(tenant.ai_features or {})
    for key, value in features.items():
        old = is_enabled(tenant, key)
        if old != bool(value):
            stored[key] = bool(value)
            changes.append({"feature": key, "old": old, "new": bool(value)})
    if stored != (tenant.ai_features or {}):
        tenant.ai_features = stored  # a new dict, so the JSON column is seen as changed
    for key, mode in reply_modes.items():
        col = REPLY_MODES[key]
        old = (getattr(tenant, col, None) or "shadow").lower()
        if old != mode:
            setattr(tenant, col, mode)
            changes.append({"feature": key, "old": old, "new": mode})
    for key, value in (thresholds or {}).items():
        col = REPLY_THRESHOLDS[key]
        old = getattr(tenant, col, None)
        if old is None or abs(float(old) - float(value)) > 1e-9:
            setattr(tenant, col, float(value))
            changes.append({"feature": f"{key}.threshold", "old": old, "new": float(value)})
    for change in changes:
        append_audit(
            db,
            tenant_id=tenant.id,
            action="ai.feature_changed",
            actor_user_id=actor_user_id,
            target_type="tenant",
            target_id=tenant.id,
            payload=change,
        )
    return changes
