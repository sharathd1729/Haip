"""Marketing agency M2: photo tags + people consent on media_assets.

Adds nullable columns (tags, tag_model, tagged_at) and people_ok BOOLEAN NOT NULL DEFAULT FALSE to an existing
tenant-scoped table (its RLS policy is unchanged). ADD COLUMN IF NOT EXISTS, so it is idempotent and repairs a table
created by create_all. Downgrade drops only these columns.

Revision ID: 160
Revises: 159
"""
from alembic import op

revision = "160"
down_revision = "159"
branch_labels = None
depends_on = None

TABLE = "media_assets"
COLUMNS = (("tags", "JSON"), ("tag_model", "VARCHAR(80)"), ("tagged_at", "TIMESTAMPTZ"),
           ("people_ok", "BOOLEAN NOT NULL DEFAULT FALSE"))


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
        for name, kind in COLUMNS:
            op.execute(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS {name} {kind}")
        return
    existing = {row[1] for row in bind.exec_driver_sql(f"PRAGMA table_info({TABLE})")}
    for name, kind in COLUMNS:
        if name not in existing:
            op.execute(f"ALTER TABLE {TABLE} ADD COLUMN {name} {kind.replace('TIMESTAMPTZ', 'TIMESTAMP')}")


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for name, _ in COLUMNS:
            op.execute(f"ALTER TABLE {TABLE} DROP COLUMN IF EXISTS {name}")
    else:
        for name, _ in COLUMNS:
            op.drop_column(TABLE, name)
