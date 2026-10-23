"""Marketing Studio phase 0 + 1 (plan 24 Oct 2026): AI images tied to their draft, ad watch-curve fields, Reel metrics,
creative tags.

  * marketing_image_jobs.content_id        -- the draft an AI image was requested for (filled into it once approved)
Nullable columns on existing tenant tables (their RLS policies are unchanged), ADD COLUMN IF NOT EXISTS, so it is
idempotent and repairs tables production built with create_all. Downgrade drops only what this adds.

Revision ID: 174
Revises: 173
Create Date: 2026-10-24
"""
from alembic import op

revision = "174"
down_revision = "173"
branch_labels = None
depends_on = None

COLUMNS = (
    ("marketing_image_jobs", "content_id", "VARCHAR"),
)


def _add_columns() -> None:
    bind = op.get_bind()
    for table, name, kind in COLUMNS:
        if bind.dialect.name == "postgresql":
            op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {kind}")
        elif name not in {row[1] for row in bind.exec_driver_sql(f"PRAGMA table_info({table})")}:
            op.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '10s'")
    _add_columns()


def downgrade():
    bind = op.get_bind()
    for table, name, _ in COLUMNS:
        if bind.dialect.name == "postgresql":
            op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {name}")
        else:
            op.drop_column(table, name)
