"""Lead scenarios (1 Nov 2026): when a lead came back, and why.

Adds columns to an existing tenant-scoped table (its RLS policy is unchanged; no new table):
  * inquiries.returned_at TIMESTAMPTZ           -- the guest got in touch again (a Lost lead reopened, or a campaign reply)
  * inquiries.returned_via VARCHAR(20)          -- came_back | campaign_reply (work queue kinds of the same names)
  * inquiries.returned_campaign_id VARCHAR      -- the WhatsApp campaign they replied to (no FK: a deleted campaign keeps it)
  * index ix_inquiries_tenant_id_returned_at
The work queue lists such a lead from returned_at (not its first arrival) until a person contacts the guest.
ADD COLUMN / CREATE INDEX IF NOT EXISTS: idempotent, and repairs a table created by create_all (prod runs create_all).

Revision ID: 182
Revises: 181
"""

from alembic import op

revision = "182"
down_revision = "181"
branch_labels = None
depends_on = None

COLUMNS = (
    ("returned_at", "TIMESTAMP WITH TIME ZONE"),
    ("returned_via", "VARCHAR(20)"),
    ("returned_campaign_id", "VARCHAR"),
)
INDEX = "ix_inquiries_tenant_id_returned_at"


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '10s'")
        for name, kind in COLUMNS:
            op.execute(f"ALTER TABLE inquiries ADD COLUMN IF NOT EXISTS {name} {kind}")
    else:
        existing = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(inquiries)")}
        for name, kind in COLUMNS:
            if name not in existing:
                op.execute(f"ALTER TABLE inquiries ADD COLUMN {name} {kind}")
    op.execute(f"CREATE INDEX IF NOT EXISTS {INDEX} ON inquiries (tenant_id, returned_at)")


def downgrade():
    bind = op.get_bind()
    op.execute(f"DROP INDEX IF EXISTS {INDEX}")
    for name, _ in reversed(COLUMNS):
        if bind.dialect.name == "postgresql":
            op.execute(f"ALTER TABLE inquiries DROP COLUMN IF EXISTS {name}")
        else:
            op.drop_column("inquiries", name)
