"""Deactivate the 'analytics' module for every existing tenant -- Owner
Dashboard, analytics pages (executive/forecasting/intelligence/sections),
and AI insights are being rebuilt from scratch (2026-08-08).

Sets workspace_modules.enabled = false for every row whose module_id maps
to modules.code = 'analytics'. Data-only: no schema change, no rows
deleted. Reversible by setting enabled back to true (or by an operator
re-running provision_default_modules once 'analytics' is added back to
DEFAULT_MODULE_CODES).

The API-side enforcement (router-level require_module("analytics") on
dashboard.py, dashboards.py, analytics_sections.py, analytics_intelligence.py,
analytics_executive.py, analytics_forecasting.py) and the Celery beat
schedule changes (compute_snapshots, run_insights, evaluate_goals,
generate_widgets commented out) ship in the same code change as this
migration.

Revision ID: 072
Revises: 071
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

revision = "072"
down_revision = "071"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text(
        """
        UPDATE workspace_modules
        SET enabled = false
        WHERE module_id IN (SELECT id FROM modules WHERE code = 'analytics')
        """
    ))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text(
        """
        UPDATE workspace_modules
        SET enabled = true
        WHERE module_id IN (SELECT id FROM modules WHERE code = 'analytics')
        """
    ))
