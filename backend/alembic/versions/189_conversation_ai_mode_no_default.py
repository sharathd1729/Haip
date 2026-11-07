"""conversations.ai_mode holds a per-thread override only (7 Nov 2026).

The column had server_default 'shadow' (migration 001) and the app copied the workspace setting into it at creation, so
1,141 Ratha threads read 'shadow' while the real mode is resolved per reply from the workspace (ai_mode_service). Now the
only stored value is 'off' (a real override); NULL = follow the workspace setting.

Schema only: drops the server default. No data is changed here; clearing old copies is
scripts/clear_derived_ai_modes.py (dry run default, --apply, one transaction per workspace so RLS context is set).
DROP DEFAULT is idempotent (prod also runs create_all). SQLite cannot alter a default: skipped (tests build from the models).

Revision ID: 189
Revises: 188
"""

from alembic import op

revision = "189"
down_revision = "188"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '10s'")
        op.execute("ALTER TABLE conversations ALTER COLUMN ai_mode DROP DEFAULT")


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE conversations ALTER COLUMN ai_mode SET DEFAULT 'shadow'")
