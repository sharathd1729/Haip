"""Staff assistant on WhatsApp (ops gap 11): the owner's on/off switch.

ops_settings.staff_assistant_enabled  NULL/FALSE = off (default: a new AI surface stays off until the owner turns it on);
                                      TRUE = a staff question on WhatsApp gets an answer from the staff member's own facts.

ops_settings already has tenant_id + forced RLS (178). ADD COLUMN IF NOT EXISTS: idempotent (prod also runs create_all,
which never adds a column to an existing table).

Revision ID: 193
Revises: 192
"""

from alembic import op

revision = "193"
down_revision = "192"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '10s'")
        op.execute("ALTER TABLE ops_settings ADD COLUMN IF NOT EXISTS staff_assistant_enabled BOOLEAN")
    elif "staff_assistant_enabled" not in {r[1] for r in bind.exec_driver_sql("PRAGMA table_info(ops_settings)")}:
        op.execute("ALTER TABLE ops_settings ADD COLUMN staff_assistant_enabled BOOLEAN")


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE ops_settings DROP COLUMN IF EXISTS staff_assistant_enabled")
