"""006 message delivery state

Adds delivery_state + delivery_error columns to messages so that
outbound send lifecycle (pending → queued → sent → delivered → read / failed)
is tracked separately from was_approved.

Revision ID: 006
Revises: 005
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None

# All valid states — kept as a plain list so we can create the type idempotently
_STATES = ["pending", "queued", "sent", "delivered", "read", "failed", "rejected"]


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return any(c["name"] == column for c in insp.get_columns(table))


def _type_exists(type_name: str) -> bool:
    """Check whether a Postgres enum type already exists (no-op on SQLite)."""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return False
    result = bind.execute(
        text("SELECT 1 FROM pg_type WHERE typname = :n"),
        {"n": type_name},
    )
    return result.fetchone() is not None


def _enum_is_uppercase(type_name: str) -> bool:
    """Return True if the first label of this PG enum is uppercase."""
    bind = op.get_bind()
    result = bind.execute(text(
        "SELECT enumlabel FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid "
        "WHERE t.typname = :n ORDER BY e.enumsortorder LIMIT 1"
    ), {"n": type_name})
    row = result.fetchone()
    return bool(row and row[0] == row[0].upper())


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # ── 1. Create/fix the Postgres enum type ─────────────────────────────────
    # SQLAlchemy may have auto-created this enum with UPPERCASE labels before
    # this migration ran. If so, drop it (no column uses it yet) and recreate
    # with lowercase so the rest of the migration works cleanly.
    if is_pg:
        if _type_exists("messagedeliverystate"):
            if _enum_is_uppercase("messagedeliverystate"):
                op.execute(text("DROP TYPE messagedeliverystate"))
                states_sql = ", ".join(f"'{s}'" for s in _STATES)
                op.execute(text(f"CREATE TYPE messagedeliverystate AS ENUM ({states_sql})"))
        else:
            states_sql = ", ".join(f"'{s}'" for s in _STATES)
            op.execute(text(f"CREATE TYPE messagedeliverystate AS ENUM ({states_sql})"))

    # ── 2. Add delivery_state column ──────────────────────────────────────────
    if not _column_exists("messages", "delivery_state"):
        if is_pg:
            op.add_column(
                "messages",
                sa.Column(
                    "delivery_state",
                    sa.Enum(*_STATES, name="messagedeliverystate"),
                    nullable=True,
                ),
            )
        else:
            # SQLite: store as plain VARCHAR
            op.add_column(
                "messages",
                sa.Column("delivery_state", sa.String(20), nullable=True),
            )

    # ── 3. Add delivery_error column ──────────────────────────────────────────
    if not _column_exists("messages", "delivery_error"):
        op.add_column(
            "messages",
            sa.Column("delivery_error", sa.Text, nullable=True),
        )

    # ── 4. Back-fill existing outbound rows ───────────────────────────────────
    if is_pg:
        op.execute(text("""
            UPDATE messages
            SET delivery_state = CASE channel_status
                WHEN 'delivered' THEN 'delivered'::messagedeliverystate
                WHEN 'read'      THEN 'read'::messagedeliverystate
                WHEN 'failed'    THEN 'failed'::messagedeliverystate
                ELSE             'sent'::messagedeliverystate
            END
            WHERE direction = 'outbound' AND delivery_state IS NULL
        """))
    else:
        op.execute(text("""
            UPDATE messages
            SET delivery_state = CASE channel_status
                WHEN 'delivered' THEN 'delivered'
                WHEN 'read'      THEN 'read'
                WHEN 'failed'    THEN 'failed'
                ELSE             'sent'
            END
            WHERE direction = 'outbound' AND delivery_state IS NULL
        """))


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if _column_exists("messages", "delivery_error"):
        op.drop_column("messages", "delivery_error")

    if _column_exists("messages", "delivery_state"):
        op.drop_column("messages", "delivery_state")

    if is_pg and _type_exists("messagedeliverystate"):
        op.execute(text("DROP TYPE messagedeliverystate"))
