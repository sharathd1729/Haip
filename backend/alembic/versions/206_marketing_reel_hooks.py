"""Marketing Studio reels: scored hook options + script (hook_plan) and the chosen hook formula (hook_formula).

marketing_content.hook_plan (JSON) + hook_formula (varchar 60). Columns only: tenant_id and RLS come from the table's own
migration. Idempotent (ADD COLUMN IF NOT EXISTS) because production runs create_all at startup.

Revision ID: 206
Revises: 205
"""
from alembic import op

revision = "206"
down_revision = "205"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE marketing_content ADD COLUMN IF NOT EXISTS hook_plan JSON")
    op.execute("ALTER TABLE marketing_content ADD COLUMN IF NOT EXISTS hook_formula VARCHAR(60)")


def downgrade():
    op.execute("ALTER TABLE marketing_content DROP COLUMN IF EXISTS hook_formula")
    op.execute("ALTER TABLE marketing_content DROP COLUMN IF EXISTS hook_plan")
