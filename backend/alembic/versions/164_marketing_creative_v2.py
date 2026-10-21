"""Marketing agency M3 (creative studio v2): critic scores on brand reviews, clip length on media assets.

Adds nullable columns to two existing tenant-scoped tables (their RLS policies are unchanged):
  * marketing_reviews.scores JSON   -- the critic's 1-5 scores (hook, specificity, voice, clarity, ask)
  * media_assets.duration_ms INTEGER -- length of an uploaded video clip, read with ffprobe (reels)
ADD COLUMN IF NOT EXISTS, so it is idempotent and repairs a table created by create_all. Downgrade drops only these.

Revision ID: 164
Revises: 163
"""
from alembic import op

revision = "164"
down_revision = "163"
branch_labels = None
depends_on = None

COLUMNS = (("marketing_reviews", "scores", "JSON"), ("media_assets", "duration_ms", "INTEGER"))


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
