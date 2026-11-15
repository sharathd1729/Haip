"""Marketing Studio: keep what the humanizer changed on each AI content version, so Undo can restore the original.

marketing_content_versions.humanize (JSON, nullable). Column only: the table's tenant_id and RLS come from its own
migration. Idempotent (ADD COLUMN IF NOT EXISTS) because production runs create_all at startup.

Revision ID: 205
Revises: 204
"""
from alembic import op

revision = "205"
down_revision = "204"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE marketing_content_versions ADD COLUMN IF NOT EXISTS humanize JSON")


def downgrade():
    op.execute("ALTER TABLE marketing_content_versions DROP COLUMN IF EXISTS humanize")
