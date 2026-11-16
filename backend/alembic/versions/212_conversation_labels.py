"""Chat labels on conversations: conversations.labels (JSON list of short strings, e.g. ["VIP", "Wedding"]).

The inbox filters on a label (GET /conversations?label=). conversations is already tenant-scoped with RLS; this only
adds a nullable column. Idempotent (ADD COLUMN IF NOT EXISTS) because production runs create_all at startup.

Revision ID: 212
Revises: 211
"""
from alembic import op

revision = "212"
down_revision = "211"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS labels JSON")


def downgrade():
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS labels")
