"""HAIP Calls app: keep each queued phone call's ingest payload so a lost call_ingest task can be queued again.

mobile_call_pending.payload (JSON) + requeue_attempts, read by mobile_calls.requeue_stuck. Columns only: the table's
tenant_id and forced RLS come from 203. Idempotent (ADD COLUMN IF NOT EXISTS) because production runs create_all at startup.

Revision ID: 204
Revises: 203
"""
from alembic import op

revision = "204"
down_revision = "203"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE mobile_call_pending ADD COLUMN IF NOT EXISTS payload JSON")
    op.execute("ALTER TABLE mobile_call_pending ADD COLUMN IF NOT EXISTS requeue_attempts INTEGER NOT NULL DEFAULT 0")


def downgrade():
    op.execute("ALTER TABLE mobile_call_pending DROP COLUMN IF EXISTS requeue_attempts")
    op.execute("ALTER TABLE mobile_call_pending DROP COLUMN IF EXISTS payload")
