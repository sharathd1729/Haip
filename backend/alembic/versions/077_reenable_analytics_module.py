"""Re-enable the 'analytics' module for every existing tenant -- this is the
rebuild migration 072's docstring said was coming (2026-08-08: "Owner
Dashboard, analytics pages... being rebuilt from scratch").

Ships alongside the new role-aware /dashboard/overview endpoint and
/dashboard page (claude-fable-5-lovely-biscuit.md). The OLD analytics
sub-pages (guests/channels/campaigns/properties/operations/ai/intent/
objections/attribution/forecasting/*) stay off-nav -- this migration only
re-enables the module flag itself, which is what the new endpoint's
require_module("analytics") gate checks. "ai_insights" (migration 075)
remains its own separate module, unaffected by this.

Data-only, mirrors 072 in reverse. Reversible via downgrade().

Revision ID: 077
Revises: 076
Create Date: 2026-08-16
"""
from alembic import op
import sqlalchemy as sa

revision = "077"
down_revision = "076"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text(
        """
        UPDATE workspace_modules
        SET enabled = true
        WHERE module_id IN (SELECT id FROM modules WHERE code = 'analytics')
        """
    ))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text(
        """
        UPDATE workspace_modules
        SET enabled = false
        WHERE module_id IN (SELECT id FROM modules WHERE code = 'analytics')
        """
    ))
