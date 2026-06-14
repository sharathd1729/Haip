"""
Seed widget_registry DB table from the 18 widgets defined in widget_service.py.
Phase 6 migration: DB becomes the source of truth; widget_service.py WIDGET_REGISTRY
will be deprecated once this table is confirmed stable.

Run once: python scripts/seed_widget_registry.py
Idempotent — skips existing widget_keys.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal
from app.models.widget_registry import WidgetRegistryEntry

# Source of truth — mirrors widget_service.py WIDGET_REGISTRY + adds module_codes
WIDGETS = [
    # key, name, description, category, widget_type, required_modules, required_metrics, min_data_rows, refresh_hours
    ("call_volume",         "Call Volume",           "Daily call count + QA trend",              "calls",     "line",    ["calls"],                         ["call_volume", "qa_avg_score"],  5,  4),
    ("sentiment",           "Call Sentiment",        "AI-scored call sentiment breakdown",        "calls",     "bar",     ["calls"],                         ["sentiment_score"],              5,  4),
    ("missed_revenue",      "Missed Revenue",        "Lost-inquiry revenue at risk",              "calls",     "kpi",     ["calls"],                         ["missed_calls", "lost_revenue"], 3,  6),
    ("objections",          "Top Objections",        "Recurring guest objection patterns",        "calls",     "table",   ["calls"],                         ["call_volume"],                  5,  6),
    ("intent_mix",          "Intent Mix",            "What guests are asking about",              "calls",     "bar",     ["calls"],                         ["call_volume"],                  10, 6),
    ("agent_leaderboard",   "Agent Leaderboard",     "Concierge QA score ranking",               "calls",     "table",   ["calls"],                         ["qa_avg_score"],                 5,  4),
    ("response_time",       "Response Time",         "p95 first-reply latency",                  "messaging", "kpi",     [],                                ["response_time", "sla_compliance"], 5, 4),
    ("channel_mix",         "Channel Mix",           "Inbound volume by channel",                "messaging", "bar",     ["whatsapp"],                      ["conversations_count"],          10, 4),
    ("campaign_performance","Campaign Performance",  "WhatsApp blast outcomes",                  "messaging", "line",    ["campaigns", "whatsapp"],         ["campaign_reach", "campaign_conversion"], 5, 6),
    ("inquiry_funnel",      "Inquiry Funnel",        "Stage-by-stage conversion",                "revenue",   "funnel",  ["leads360"],                      ["inquiry_funnel", "active_inquiries"], 10, 6),
    ("attribution",         "Lead Attribution",      "Which sources drive bookings",             "revenue",   "bar",     ["leads360"],                      ["lead_conversion"],              10, 24),
    ("occupancy_forecast",  "Occupancy Forecast",    "30-day forward occupancy",                 "revenue",   "line",    ["channel_manager", "analytics"],  ["occupancy_pct"],                10, 24),
    ("revenue_forecast",    "Revenue Forecast",      "30-day projected revenue",                 "revenue",   "line",    ["channel_manager", "analytics"],  ["revenue_mtd"],                  10, 24),
    ("pricing",             "Pricing Signals",       "Rate vs. occupancy optimisation",          "revenue",   "line",    ["channel_manager", "analytics"],  ["adr", "revpar"],                10, 24),
    ("guest_ltv",           "Guest LTV",             "Lifetime revenue per guest",               "guests",    "kpi",     ["channel_manager"],               ["guest_ltv"],                    20, 24),
    ("churn_risk",          "Churn Risk",            "Guests likely not to return",              "guests",    "table",   ["channel_manager", "analytics"],  ["churn_risk"],                   10, 24),
    ("cohorts",             "Guest Cohorts",         "Repeat vs. new guest trends",             "guests",    "bar",     ["channel_manager", "analytics"],  [],                               20, 24),
    ("ai_recommendations",  "AI Recommendations",    "Prioritised action suggestions",           "ai",        "table",   [],                                [],                               0,  6),
]


def seed():
    with SessionLocal() as db:
        existing = {r.widget_key for r in db.query(WidgetRegistryEntry.widget_key).all()}
        added = 0
        for (key, name, desc, cat, wtype, req_modules, req_metrics, min_rows, refresh_h) in WIDGETS:
            if key not in existing:
                db.add(WidgetRegistryEntry(
                    widget_key=key,
                    widget_name=name,
                    description=desc,
                    category=cat,
                    widget_type=wtype,
                    required_modules=req_modules,
                    required_metrics=req_metrics,
                    required_feature_flags=[],
                    default_metric_bindings={},
                    min_data_rows=min_rows,
                    refresh_hours=refresh_h,
                    is_system=True,
                ))
                added += 1
        db.commit()
        print(f"Seeded {added} widgets. Skipped {len(WIDGETS) - added} existing.")


if __name__ == "__main__":
    seed()
