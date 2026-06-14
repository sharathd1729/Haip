"""
Seed metrics_registry and modules tables from the Module Registry architecture.
Run once: python scripts/seed_metrics_registry.py

Idempotent — uses ON CONFLICT DO NOTHING on metric_key PK.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal
from app.models.metric_registry import MetricRegistry
from app.models.module import Module
from app.models.base import gen_uuid

MODULES = [
    {"code": "whatsapp",         "name": "WhatsApp",          "category": "messaging"},
    {"code": "instagram",        "name": "Instagram DM",       "category": "messaging"},
    {"code": "channel_manager",  "name": "Channel Manager",    "category": "revenue"},
    {"code": "calls",            "name": "Calls / IVR",        "category": "calls"},
    {"code": "leads360",         "name": "Leads 360",          "category": "crm"},
    {"code": "analytics",        "name": "AI Analytics",       "category": "ai"},
    {"code": "ask_haip",         "name": "Ask HAIP",           "category": "ai"},
    {"code": "ai_concierge",     "name": "AI Concierge",       "category": "ai"},
    {"code": "campaigns",        "name": "Campaigns",          "category": "messaging"},
    {"code": "flow_builder",     "name": "Flow Builder",       "category": "messaging"},
]

METRICS = [
    # WhatsApp
    ("conversations_count",   "Conversations Count",      "whatsapp",        "count",  "count"),
    ("response_time",         "Response Time",            "whatsapp",        "avg",    "seconds"),
    ("ai_draft_rate",         "AI Draft Rate",            "whatsapp",        "ratio",  "%"),
    ("wa_lead_conversion",    "WA Lead Conversion",       "whatsapp",        "ratio",  "%"),
    ("template_delivery_rate","Template Delivery Rate",   "whatsapp",        "ratio",  "%"),
    ("read_rate",             "Read Rate",                "whatsapp",        "ratio",  "%"),

    # Instagram
    ("dm_count",              "DM Count",                 "instagram",       "count",  "count"),
    ("ig_response_time",      "IG Response Time",         "instagram",       "avg",    "seconds"),
    ("ig_lead_count",         "IG Lead Count",            "instagram",       "count",  "count"),
    ("ig_conversion_rate",    "IG Conversion Rate",       "instagram",       "ratio",  "%"),
    ("story_reply_count",     "Story Reply Count",        "instagram",       "count",  "count"),

    # Channel Manager
    ("bookings_count",        "Bookings Count",           "channel_manager", "count",  "count"),
    ("occupancy_pct",         "Occupancy %",              "channel_manager", "avg",    "%"),
    ("revenue_mtd",           "Revenue MTD",              "channel_manager", "sum",    "INR"),
    ("adr",                   "Average Daily Rate",       "channel_manager", "avg",    "INR"),
    ("revpar",                "RevPAR",                   "channel_manager", "avg",    "INR"),
    ("lost_revenue",          "Lost Revenue",             "channel_manager", "sum",    "INR"),
    ("guest_ltv",             "Guest LTV",                "channel_manager", "avg",    "INR"),

    # Calls / IVR
    ("call_volume",           "Call Volume",              "calls",           "count",  "count"),
    ("call_duration",         "Call Duration",            "calls",           "avg",    "seconds"),
    ("call_conversion",       "Call Conversion",          "calls",           "ratio",  "%"),
    ("missed_calls",          "Missed Calls",             "calls",           "count",  "count"),
    ("qa_avg_score",          "QA Average Score",         "calls",           "avg",    "%"),
    ("sentiment_score",       "Sentiment Score",          "calls",           "avg",    "score"),

    # Leads 360
    ("active_inquiries",      "Active Inquiries",         "leads360",        "count",  "count"),
    ("inquiry_funnel",        "Inquiry Funnel",           "leads360",        "count",  "count"),
    ("lead_conversion",       "Lead Conversion",          "leads360",        "ratio",  "%"),
    ("response_time_p95",     "Response Time P95",        "leads360",        "p95",    "seconds"),
    ("sla_compliance",        "SLA Compliance",           "leads360",        "ratio",  "%"),
    ("lost_reasons",          "Lost Reasons",             "leads360",        "count",  "count"),

    # AI Analytics
    ("anomaly_scores",        "Anomaly Scores",           "analytics",       "avg",    "score"),
    ("ai_insights",           "AI Insights",              "analytics",       "count",  "count"),
    ("forecasts",             "Forecasts",                "analytics",       "count",  "count"),
    ("cohort_analysis",       "Cohort Analysis",          "analytics",       "count",  "count"),
    ("churn_risk",            "Churn Risk",               "analytics",       "avg",    "score"),
    ("pricing_rec",           "Pricing Recommendations",  "analytics",       "count",  "count"),

    # AI Concierge
    ("draft_acceptance_rate", "Draft Acceptance Rate",    "ai_concierge",    "ratio",  "%"),
    ("ai_response_count",     "AI Response Count",        "ai_concierge",    "count",  "count"),
    ("concierge_conversion",  "Concierge Conversion",     "ai_concierge",    "ratio",  "%"),
    ("escalation_rate",       "Escalation Rate",          "ai_concierge",    "ratio",  "%"),

    # Campaigns
    ("campaign_reach",        "Campaign Reach",           "campaigns",       "count",  "count"),
    ("campaign_conversion",   "Campaign Conversion",      "campaigns",       "ratio",  "%"),
    ("cost_per_lead",         "Cost Per Lead",            "campaigns",       "avg",    "INR"),
    ("roas",                  "Return on Ad Spend",       "campaigns",       "ratio",  "x"),
    ("template_performance",  "Template Performance",     "campaigns",       "avg",    "%"),

    # Flow Builder
    ("flow_triggers",         "Flow Triggers",            "flow_builder",    "count",  "count"),
    ("flow_completions",      "Flow Completions",         "flow_builder",    "count",  "count"),
    ("flow_drop_rate",        "Flow Drop Rate",           "flow_builder",    "ratio",  "%"),
    ("automation_count",      "Automation Count",         "flow_builder",    "count",  "count"),
]


def seed():
    with SessionLocal() as db:
        # ── Modules ───────────────────────────────────────────────────────────
        existing_codes = {r.code for r in db.query(Module.code).all()}
        added_modules = 0
        for m in MODULES:
            if m["code"] not in existing_codes:
                db.add(Module(
                    id=gen_uuid(),
                    code=m["code"],
                    name=m["name"],
                    category=m["category"],
                    status="active",
                    requires_modules=[],
                ))
                added_modules += 1

        # ── Metrics ───────────────────────────────────────────────────────────
        existing_keys = {r.metric_key for r in db.query(MetricRegistry.metric_key).all()}
        added_metrics = 0
        for metric_key, name, module_code, agg_type, unit in METRICS:
            if metric_key not in existing_keys:
                db.add(MetricRegistry(
                    metric_key=metric_key,
                    metric_name=name,
                    module_code=module_code,
                    aggregation_type=agg_type,
                    unit=unit,
                    required_tables=[],
                    compatible_widget_types=[],
                    refresh_frequency=3600,
                    cache_ttl_seconds=900,
                    is_system=True,
                ))
                added_metrics += 1

        db.commit()
        print(f"Seeded {added_modules} modules, {added_metrics} metrics.")
        print(f"Skipped {len(MODULES) - added_modules} existing modules, "
              f"{len(METRICS) - added_metrics} existing metrics.")


if __name__ == "__main__":
    seed()
