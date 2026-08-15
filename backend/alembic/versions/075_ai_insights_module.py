"""New 'ai_insights' module, decoupled from the still-off 'analytics'
module -- reactivating the AI Insights feed (insight_detector.py,
Insight model, GET/POST /analytics/insights) as its own switch rather
than as part of the broader analytics rebuild, per the user's explicit
request for a standalone dynamic recommendations feed distinct from
metric-tile dashboards.

Mirrors migration 031's module-seed pattern. Provisions every existing
tenant with the module enabled (matches DEFAULT_MODULE_CODES going
forward for new tenants, set in the same code change as this migration).

Revision ID: 075
Revises: 074
Create Date: 2026-08-15
"""
from alembic import op
import sqlalchemy as sa

revision = "075"
down_revision = "074"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    bind.execute(sa.text("""
        INSERT INTO modules (id, code, name, description, category, status, requires_modules)
        VALUES (
            gen_random_uuid()::text, 'ai_insights', 'AI Insights',
            'Live feed of AI-generated recommendations and alerts (missed follow-ups, cold leads, stale quotes, etc.)',
            'ai', 'active', '[]'
        )
    """))

    bind.execute(sa.text("""
        INSERT INTO workspace_modules (id, workspace_id, module_id, enabled)
        SELECT gen_random_uuid()::text, t.id, m.id, true
        FROM tenants t
        CROSS JOIN modules m
        WHERE m.code = 'ai_insights'
        ON CONFLICT (workspace_id, module_id) DO NOTHING
    """))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("""
        DELETE FROM workspace_modules
        WHERE module_id IN (SELECT id FROM modules WHERE code = 'ai_insights')
    """))
    bind.execute(sa.text("DELETE FROM modules WHERE code = 'ai_insights'"))
