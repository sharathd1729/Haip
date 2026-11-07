"""Guest ops tickets (8 Nov 2026): ops_items.source_ref, the idempotency key of what opened a ticket.

A guest's in-stay problem in chat ("msg:<message id>") and a booking's service request ("ssr:<request id>") now open an
ops item (services/guest_ops_tickets.py). The same message or request must never open two tickets, so:
  * ops_items.source_ref VARCHAR(120) NULL
  * unique index uq_ops_items_source_ref ON ops_items (tenant_id, source_ref) WHERE source_ref IS NOT NULL
Existing tenant-scoped table: its RLS policy is unchanged (no new table). The new item status "confirming" is a value of
the existing VARCHAR(15) status column (no schema change).
ADD COLUMN / CREATE UNIQUE INDEX IF NOT EXISTS: idempotent, and repairs a table created by create_all (prod runs create_all).

Revision ID: 190
Revises: 189
"""

from alembic import op

revision = "190"
down_revision = "189"
branch_labels = None
depends_on = None

INDEX = "uq_ops_items_source_ref"


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '10s'")
        op.execute("ALTER TABLE ops_items ADD COLUMN IF NOT EXISTS source_ref VARCHAR(120)")
    else:
        existing = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(ops_items)")}
        if "source_ref" not in existing:
            op.execute("ALTER TABLE ops_items ADD COLUMN source_ref VARCHAR(120)")
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX} ON ops_items (tenant_id, source_ref) WHERE source_ref IS NOT NULL"
    )


def downgrade():
    bind = op.get_bind()
    op.execute(f"DROP INDEX IF EXISTS {INDEX}")
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE ops_items DROP COLUMN IF EXISTS source_ref")
    else:
        op.drop_column("ops_items", "source_ref")
