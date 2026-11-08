"""Review request (ops gap 2): the owner's on/off switch for the day-after-check-out "how was your stay?" message.

ops_settings.review_request_enabled  NULL = on once the haip_review_request_v1 template is approved, else off;
                                      TRUE/FALSE = the owner's choice.

The guest's answer reuses ops_auto_messages.response (190): "1"-"5" or "feedback". ops_settings already has tenant_id +
forced RLS (178). ADD COLUMN IF NOT EXISTS: idempotent (prod also runs create_all, which never adds a column to an
existing table).

Revision ID: 192
Revises: 191
"""

from alembic import op

revision = "192"
down_revision = "191"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '10s'")
        op.execute("ALTER TABLE ops_settings ADD COLUMN IF NOT EXISTS review_request_enabled BOOLEAN")
    elif "review_request_enabled" not in {r[1] for r in bind.exec_driver_sql("PRAGMA table_info(ops_settings)")}:
        op.execute("ALTER TABLE ops_settings ADD COLUMN review_request_enabled BOOLEAN")


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE ops_settings DROP COLUMN IF EXISTS review_request_enabled")
