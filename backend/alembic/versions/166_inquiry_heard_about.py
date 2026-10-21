"""Marketing agency M6 (measurement): what a guest says when asked "How did you first hear about us?".

Adds nullable columns to an existing tenant-scoped table (its RLS policy is unchanged):
  * inquiries.heard_about VARCHAR(30)       -- the answer, one of marketing_attribution.HEARD_ABOUT
  * inquiries.heard_about_note VARCHAR(200) -- their own words, when they add any
ADD COLUMN IF NOT EXISTS, so it is idempotent and repairs a table created by create_all. Downgrade drops only these.

Revision ID: 166
Revises: 165
"""
from alembic import op

revision = "166"
down_revision = "165"
branch_labels = None
depends_on = None

COLUMNS = (("inquiries", "heard_about", "VARCHAR(30)"), ("inquiries", "heard_about_note", "VARCHAR(200)"))


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '10s'")
        for table, name, kind in COLUMNS:
            op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {kind}")
        return
    for table, name, kind in COLUMNS:
        existing = {row[1] for row in bind.exec_driver_sql(f"PRAGMA table_info({table})")}
        if name not in existing:
            op.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")


def downgrade():
    bind = op.get_bind()
    for table, name, _ in COLUMNS:
        if bind.dialect.name == "postgresql":
            op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {name}")
        else:
            op.drop_column(table, name)
