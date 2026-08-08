"""Remap dashboard_widget_instances rows still on legacy widget_service.py
WIDGET_REGISTRY keys onto the canonical migration-032 widget_registry keys
(HAIP_Dashboard_Metrics_Plan.md Phase 2, step 2.4 -- renumbered from the
plan's "071", see 069's docstring for why)

F2: widget_service.py's WIDGET_REGISTRY (19 hardcoded Python keys) and the
widget_registry table (25 rows, migration 032) both describe the same
widgets under different keys in five cases. dashboards.py's dashboard-v2
endpoints already resolve DashboardWidgetInstance.widget_key against the
DB-driven widget_registry table (WidgetRegistryEntry) -- any instance row
still on a legacy key silently fails that lookup (reg_map.get() returns
None), which means eligibility/min_data_rows enforcement is quietly
skipped for it. This is the one-time catch-up; canonical names are the
migration-032 set per the plan's own stated resolution rule ("if this
table and the code disagree, the code wins" -- here widget_registry is
the code's actual DB source of truth for dashboards.py).

Revision ID: 070
Revises: 069
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

revision = "070"
down_revision = "069"
branch_labels = None
depends_on = None

_KEY_MAP = {
    "sentiment": "call_sentiment",
    "objections": "top_objections",
    "attribution": "lead_attribution",
    "cohorts": "guest_cohorts",
    "pricing": "pricing_signals",
}


def upgrade():
    bind = op.get_bind()
    for legacy, canonical in _KEY_MAP.items():
        bind.execute(
            sa.text(
                "UPDATE dashboard_widget_instances SET widget_key = :canonical WHERE widget_key = :legacy"
            ),
            {"canonical": canonical, "legacy": legacy},
        )


def downgrade():
    """Not reversible -- no record of which rows this remapped versus were
    already on the canonical key (e.g. a tenant genuinely named a custom
    widget instance 'sentiment'). Leaving rows on the canonical key is the
    safe choice; it's the key dashboards.py actually resolves against."""
    pass
