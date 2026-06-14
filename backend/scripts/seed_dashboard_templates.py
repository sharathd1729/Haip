"""
Seed 6 system dashboard templates per the architecture:
Owner, Sales, Operations, Marketing, Guest360, Revenue.

Run once: python scripts/seed_dashboard_templates.py
Idempotent — skips existing template_keys.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal
from app.models.dashboard_v2 import DashboardTemplate
from app.models.base import gen_uuid

TEMPLATES = [
    {
        "template_key": "owner_daily",
        "name": "Owner Daily",
        "description": "Revenue, occupancy, and team performance at a glance for property owners.",
        "required_modules": ["channel_manager", "calls"],
        "target_roles": ["owner"],
        "default_date_range": "7d",
        "layout_json": {
            "widgets": [
                {"widget_key": "revenue_forecast",      "position": {"lg": {"col": 0, "row": 0, "w": 4, "h": 2}}},
                {"widget_key": "occupancy_forecast",    "position": {"lg": {"col": 4, "row": 0, "w": 4, "h": 2}}},
                {"widget_key": "call_volume",           "position": {"lg": {"col": 8, "row": 0, "w": 4, "h": 2}}},
                {"widget_key": "agent_leaderboard",     "position": {"lg": {"col": 0, "row": 2, "w": 6, "h": 4}}},
                {"widget_key": "objections",            "position": {"lg": {"col": 6, "row": 2, "w": 6, "h": 4}}},
                {"widget_key": "missed_revenue",        "position": {"lg": {"col": 0, "row": 6, "w": 6, "h": 3}}},
                {"widget_key": "ai_recommendations",   "position": {"lg": {"col": 6, "row": 6, "w": 6, "h": 3}}},
            ]
        },
    },
    {
        "template_key": "sales_pipeline",
        "name": "Sales Pipeline",
        "description": "Leads360 funnel, conversion rates, and team response times.",
        "required_modules": ["leads360"],
        "target_roles": ["owner", "manager"],
        "default_date_range": "30d",
        "layout_json": {
            "widgets": [
                {"widget_key": "inquiry_funnel",        "position": {"lg": {"col": 0, "row": 0, "w": 6, "h": 4}}},
                {"widget_key": "intent_mix",            "position": {"lg": {"col": 6, "row": 0, "w": 6, "h": 4}}},
                {"widget_key": "response_time",         "position": {"lg": {"col": 0, "row": 4, "w": 4, "h": 3}}},
                {"widget_key": "channel_mix",           "position": {"lg": {"col": 4, "row": 4, "w": 4, "h": 3}}},
                {"widget_key": "objections",            "position": {"lg": {"col": 8, "row": 4, "w": 4, "h": 3}}},
                {"widget_key": "attribution",           "position": {"lg": {"col": 0, "row": 7, "w": 12, "h": 3}}},
            ]
        },
    },
    {
        "template_key": "operations",
        "name": "Operations",
        "description": "Call QA, agent scorecards, SLA compliance, and missed revenue.",
        "required_modules": ["calls"],
        "target_roles": ["owner", "manager"],
        "default_date_range": "7d",
        "layout_json": {
            "widgets": [
                {"widget_key": "call_volume",           "position": {"lg": {"col": 0, "row": 0, "w": 3, "h": 2}}},
                {"widget_key": "sentiment",             "position": {"lg": {"col": 3, "row": 0, "w": 3, "h": 2}}},
                {"widget_key": "missed_revenue",        "position": {"lg": {"col": 6, "row": 0, "w": 3, "h": 2}}},
                {"widget_key": "response_time",         "position": {"lg": {"col": 9, "row": 0, "w": 3, "h": 2}}},
                {"widget_key": "agent_leaderboard",     "position": {"lg": {"col": 0, "row": 2, "w": 8, "h": 5}}},
                {"widget_key": "objections",            "position": {"lg": {"col": 8, "row": 2, "w": 4, "h": 5}}},
                {"widget_key": "ai_recommendations",   "position": {"lg": {"col": 0, "row": 7, "w": 12, "h": 3}}},
            ]
        },
    },
    {
        "template_key": "marketing",
        "name": "Marketing",
        "description": "Campaign performance, channel mix, ROAS, and WhatsApp engagement.",
        "required_modules": ["campaigns", "whatsapp"],
        "target_roles": ["owner", "manager"],
        "default_date_range": "30d",
        "layout_json": {
            "widgets": [
                {"widget_key": "campaign_performance",  "position": {"lg": {"col": 0, "row": 0, "w": 6, "h": 4}}},
                {"widget_key": "channel_mix",           "position": {"lg": {"col": 6, "row": 0, "w": 6, "h": 4}}},
                {"widget_key": "attribution",           "position": {"lg": {"col": 0, "row": 4, "w": 8, "h": 4}}},
                {"widget_key": "intent_mix",            "position": {"lg": {"col": 8, "row": 4, "w": 4, "h": 4}}},
                {"widget_key": "ai_recommendations",   "position": {"lg": {"col": 0, "row": 8, "w": 12, "h": 3}}},
            ]
        },
    },
    {
        "template_key": "guest360",
        "name": "Guest 360",
        "description": "Guest LTV, churn risk, cohort analysis, and sentiment scores.",
        "required_modules": ["channel_manager", "analytics"],
        "target_roles": ["owner", "manager"],
        "default_date_range": "90d",
        "layout_json": {
            "widgets": [
                {"widget_key": "guest_ltv",             "position": {"lg": {"col": 0, "row": 0, "w": 6, "h": 4}}},
                {"widget_key": "churn_risk",            "position": {"lg": {"col": 6, "row": 0, "w": 6, "h": 4}}},
                {"widget_key": "cohorts",               "position": {"lg": {"col": 0, "row": 4, "w": 8, "h": 5}}},
                {"widget_key": "sentiment",             "position": {"lg": {"col": 8, "row": 4, "w": 4, "h": 5}}},
                {"widget_key": "ai_recommendations",   "position": {"lg": {"col": 0, "row": 9, "w": 12, "h": 3}}},
            ]
        },
    },
    {
        "template_key": "revenue",
        "name": "Revenue",
        "description": "RevPAR, ADR, occupancy forecast, revenue trend, and pricing recommendations.",
        "required_modules": ["channel_manager", "analytics"],
        "target_roles": ["owner"],
        "default_date_range": "30d",
        "layout_json": {
            "widgets": [
                {"widget_key": "revenue_forecast",      "position": {"lg": {"col": 0, "row": 0, "w": 4, "h": 3}}},
                {"widget_key": "occupancy_forecast",    "position": {"lg": {"col": 4, "row": 0, "w": 4, "h": 3}}},
                {"widget_key": "pricing",               "position": {"lg": {"col": 8, "row": 0, "w": 4, "h": 3}}},
                {"widget_key": "attribution",           "position": {"lg": {"col": 0, "row": 3, "w": 8, "h": 4}}},
                {"widget_key": "channel_mix",           "position": {"lg": {"col": 8, "row": 3, "w": 4, "h": 4}}},
                {"widget_key": "ai_recommendations",   "position": {"lg": {"col": 0, "row": 7, "w": 12, "h": 3}}},
            ]
        },
    },
]


def seed():
    with SessionLocal() as db:
        existing = {r.template_key for r in db.query(DashboardTemplate.template_key).all()}
        added = 0
        for t in TEMPLATES:
            if t["template_key"] not in existing:
                db.add(DashboardTemplate(
                    id=gen_uuid(),
                    template_key=t["template_key"],
                    name=t["name"],
                    description=t["description"],
                    required_modules=t["required_modules"],
                    layout_json=t["layout_json"],
                    default_date_range=t["default_date_range"],
                    target_roles=t["target_roles"],
                    is_system=True,
                    workspace_id=None,
                ))
                added += 1
        db.commit()
        print(f"Seeded {added} templates. Skipped {len(TEMPLATES) - added} existing.")


if __name__ == "__main__":
    seed()
