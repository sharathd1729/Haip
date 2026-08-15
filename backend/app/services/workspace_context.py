"""
WorkspaceContext — resolves active modules and feature flags for a workspace.

This is the single source of truth for module-gating decisions.
All endpoints, widgets, metrics, and Ask HAIP read from this context.

Resolution order for feature flags (highest priority wins):
  manual override > plan entitlement > module subscription > global default
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import uuid
import structlog

from sqlalchemy.orm import Session

log = structlog.get_logger()

# ── Module → flag derivation map ─────────────────────────────────────────────
# When a module is active, these flags are automatically set to True.
MODULE_FLAG_MAP: dict[str, list[str]] = {
    "whatsapp":       ["whatsapp_enabled"],
    "instagram":      ["instagram_enabled"],
    "calls":          ["calls_enabled", "call_transcription_enabled", "call_qa_enabled",
                       "missed_call_alerts_enabled"],
    "leads360":       ["leads360_enabled", "pipeline_view_enabled", "sla_alerts_enabled"],
    "channel_manager":["channel_manager_enabled", "revenue_reporting_enabled"],
    "analytics":      ["analytics_enabled", "ai_analytics_enabled", "anomaly_detection_enabled"],
    "ask_haip":       ["ask_haip_enabled"],
    "ai_concierge":   ["ai_concierge_enabled", "ai_drafts_enabled"],
    "campaigns":      ["campaign_builder_enabled"],
    "flow_builder":   ["flow_builder_enabled"],
    # AI Insights feed reactivated (2026-08-15) as its own switch, decoupled
    # from "analytics" (still deliberately off pending its own rebuild) --
    # ai_insights_enabled moved here from analytics's bundle above.
    "ai_insights":    ["ai_insights_enabled"],
}

# Flags that require BOTH module AND plan (Scale/Enterprise)
PLAN_GATED_FLAGS: dict[str, list[str]] = {
    "Scale":      ["forecasting_enabled", "cohort_analysis_enabled",
                   "occupancy_forecast_enabled", "churn_risk_enabled"],
    "Enterprise": ["forecasting_enabled", "cohort_analysis_enabled",
                   "occupancy_forecast_enabled", "churn_risk_enabled"],
}

# Modules every workspace gets by default today (no paid module-selection
# flow exists yet — see Phase 1 "Choose Modules" onboarding step). Used both
# to backfill pre-existing tenants (migration 035) and to provision new
# tenants at registration, so no workspace is ever left with zero rows.
#
# "analytics" deliberately excluded (2026-08-08) -- Owner Dashboard and
# analytics pages are deactivated pending a from-scratch rebuild (migration
# 072 disabled it for existing tenants). Re-add here once the rebuild ships.
# "ai_insights" is a separate switch (2026-08-15, migration 075) -- the
# AI Insights feed was reactivated independently of the broader analytics
# rebuild, so it's back in the default set for new tenants.
DEFAULT_MODULE_CODES: list[str] = [
    "whatsapp", "instagram", "calls", "leads360", "channel_manager",
    "ask_haip", "ai_concierge", "campaigns", "flow_builder", "ai_insights",
    # Re-added 2026-08-16 -- the role-aware dashboard rebuild (migration 077)
    # is what migration 072's "removed pending rebuild" comment was waiting
    # on. New tenants now get it provisioned like everything else above.
    "analytics",
]


def provision_default_modules(db: Session, workspace_id: str, activated_by: Optional[str] = None) -> None:
    """
    Insert workspace_modules rows for the default module set, if not already
    present. Idempotent — safe to call on every tenant creation.
    """
    from app.models.module import Module, WorkspaceModule

    already = {
        row.module_id for row in
        db.query(WorkspaceModule.module_id).filter(WorkspaceModule.workspace_id == workspace_id).all()
    }
    modules = db.query(Module).filter(Module.code.in_(DEFAULT_MODULE_CODES)).all()
    for module in modules:
        if module.id in already:
            continue
        db.add(WorkspaceModule(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            module_id=module.id,
            enabled=True,
            activated_by=activated_by,
        ))


@dataclass
class WorkspaceContext:
    workspace_id: str
    active_modules: list[str] = field(default_factory=list)
    flags: dict[str, bool] = field(default_factory=dict)
    plan: str = "growth"

    def has_module(self, *module_codes: str) -> bool:
        """Return True if ALL listed modules are active."""
        return all(m in self.active_modules for m in module_codes)

    def flag(self, key: str) -> bool:
        return self.flags.get(key, False)

    def available_metric_modules(self) -> set[str]:
        return set(self.active_modules)


def load_workspace_context(db: Session, workspace_id: str) -> WorkspaceContext:
    """
    Build WorkspaceContext from DB.
    Caller is responsible for caching (Redis TTL 5min recommended).
    """
    from app.models.module import Module, WorkspaceModule
    from app.models.feature_flag import FeatureFlag
    from app.models.tenant import Tenant

    tenant = db.query(Tenant).filter(Tenant.id == workspace_id).first()
    plan = tenant.plan if tenant else "growth"

    # 1. Load active module codes
    rows = (
        db.query(Module.code)
        .join(WorkspaceModule, WorkspaceModule.module_id == Module.id)
        .filter(
            WorkspaceModule.workspace_id == workspace_id,
            WorkspaceModule.enabled == True,
        )
        .all()
    )
    active_modules = [r.code for r in rows]

    # 2. Derive flags from modules
    derived: dict[str, bool] = {}
    for mod_code in active_modules:
        for flag in MODULE_FLAG_MAP.get(mod_code, []):
            derived[flag] = True

    # 3. Apply plan-gated flags
    for plan_key, flags in PLAN_GATED_FLAGS.items():
        if plan.lower() in (plan_key.lower(),):
            for flag in flags:
                if flag not in derived:
                    derived[flag] = True

    # 4. Load manual overrides from DB (source=manual takes priority)
    manual_rows = (
        db.query(FeatureFlag)
        .filter(FeatureFlag.workspace_id == workspace_id, FeatureFlag.source == "manual")
        .all()
    )
    for row in manual_rows:
        derived[row.flag_key] = row.value

    # 5. Fill in global defaults for any flag not yet set
    global_defaults = (
        db.query(FeatureFlag)
        .filter(FeatureFlag.workspace_id == None)
        .all()
    )
    for row in global_defaults:
        if row.flag_key not in derived:
            derived[row.flag_key] = row.value

    log.info("workspace_context_loaded",
             workspace_id=workspace_id,
             modules=active_modules,
             flag_count=len(derived))

    return WorkspaceContext(
        workspace_id=workspace_id,
        active_modules=active_modules,
        flags=derived,
        plan=plan,
    )


def available_metrics_for_context(db: Session, ctx: WorkspaceContext) -> list[dict]:
    """
    Return all metric registry rows whose module_code is in active_modules.
    Used by Ask HAIP to build the system prompt and by the Metrics API.
    """
    from app.models.metric_registry import MetricRegistry

    rows = (
        db.query(MetricRegistry)
        .filter(MetricRegistry.module_code.in_(ctx.active_modules))
        .all()
    )
    return [
        {
            "key": r.metric_key,
            "name": r.metric_name,
            "description": r.description,
            "module": r.module_code,
            "unit": r.unit,
            "aggregation": r.aggregation_type,
        }
        for r in rows
    ]


def available_widgets_for_context(db: Session, ctx: WorkspaceContext) -> list[dict]:
    """
    Return widget registry rows filtered to those whose required_modules
    are all in active_modules and required_feature_flags are all True.
    """
    from app.models.widget_registry import WidgetRegistryEntry

    all_widgets = db.query(WidgetRegistryEntry).all()
    result = []
    for w in all_widgets:
        req_modules: list[str] = w.required_modules or []
        req_flags: list[str] = w.required_feature_flags or []

        modules_ok = all(m in ctx.active_modules for m in req_modules)
        flags_ok = all(ctx.flag(f) for f in req_flags)

        result.append({
            "key": w.widget_key,
            "name": w.widget_name,
            "description": w.description,
            "category": w.category,
            "widget_type": w.widget_type,
            "available": modules_ok and flags_ok,
            "missing_modules": [m for m in req_modules if m not in ctx.active_modules],
            "missing_flags": [f for f in req_flags if not ctx.flag(f)],
            "min_data_rows": w.min_data_rows,
        })
    return result


def available_templates_for_context(db: Session, ctx: WorkspaceContext) -> list[dict]:
    """Return dashboard templates whose required_modules are all active."""
    from app.models.dashboard_v2 import DashboardTemplate

    templates = db.query(DashboardTemplate).filter(
        (DashboardTemplate.workspace_id == None) |
        (DashboardTemplate.workspace_id == ctx.workspace_id)
    ).all()

    result = []
    for t in templates:
        req: list[str] = t.required_modules or []
        available = all(m in ctx.active_modules for m in req)
        result.append({
            "template_key": t.template_key,
            "name": t.name,
            "description": t.description,
            "available": available,
            "missing_modules": [m for m in req if m not in ctx.active_modules],
            "layout_json": t.layout_json,
            "default_date_range": t.default_date_range,
            "target_roles": t.target_roles,
        })
    return result
