"""Mid-stay check (ops gap 9): the owner's on/off switch and the guest's answer.

ops_settings.midstay_check_enabled  NULL = on once the haip_midstay_check_v1 template is approved, else off; TRUE/FALSE =
                                     the owner's choice.
ops_auto_messages.response           positive | problem: the guest's first answer to the day-2 check (NULL = none yet).

Both tables already have tenant_id + forced RLS (178, 180). ADD COLUMN IF NOT EXISTS: idempotent (prod also runs
create_all, which never adds a column to an existing table).

Revision ID: 190
Revises: 189
"""

from alembic import op

revision = "190"
down_revision = "189"
branch_labels = None
depends_on = None


COLUMNS = (("ops_settings", "midstay_check_enabled", "BOOLEAN"), ("ops_auto_messages", "response", "VARCHAR(10)"))


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
    for table, column, kind in COLUMNS:
        if postgres:
            op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {kind}")
        elif column not in {r[1] for r in bind.exec_driver_sql(f"PRAGMA table_info({table})")}:
            op.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        for table, column, _kind in COLUMNS:
            op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
