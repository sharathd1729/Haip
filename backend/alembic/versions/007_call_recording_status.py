"""007 call recording status

Adds recording_status + recording_error columns to calls so the
recording fetch pipeline has a durable, inspectable state machine
instead of relying on the boolean recording_fetched flag.

Revision ID: 007
Revises: 006
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None

_STATES = [
    "pending",
    "fetching",
    "available",
    "missing_retry_1",
    "missing_retry_2",
    "missing_retry_3",
    "permanently_missing",
]


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return any(c["name"] == column for c in insp.get_columns(table))


def _type_exists(type_name: str) -> bool:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return False
    result = bind.execute(
        text("SELECT 1 FROM pg_type WHERE typname = :n"),
        {"n": type_name},
    )
    return result.fetchone() is not None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # ── 1. Create Postgres enum type ──────────────────────────────────────────
    if is_pg and not _type_exists("recordingstatus"):
        states_sql = ", ".join(f"'{s}'" for s in _STATES)
        op.execute(text(f"CREATE TYPE recordingstatus AS ENUM ({states_sql})"))

    # ── 2. Add recording_status column ────────────────────────────────────────
    if not _column_exists("calls", "recording_status"):
        if is_pg:
            op.add_column(
                "calls",
                sa.Column(
                    "recording_status",
                    sa.Enum(*_STATES, name="recordingstatus"),
                    nullable=True,
                    server_default="pending",
                ),
            )
        else:
            op.add_column(
                "calls",
                sa.Column("recording_status", sa.String(30), nullable=True,
                          server_default="pending"),
            )

    # ── 3. Add recording_error column ─────────────────────────────────────────
    if not _column_exists("calls", "recording_error"):
        op.add_column(
            "calls",
            sa.Column("recording_error", sa.Text, nullable=True),
        )

    # ── 4. Back-fill existing rows ────────────────────────────────────────────
    # Rows with recording_fetched=true → 'available'
    # Rows with recording_fetched=false and transcription_status='failed' → 'permanently_missing'
    # Everything else → 'pending'
    if is_pg:
        op.execute(text("""
            UPDATE calls SET recording_status =
              CASE
                WHEN recording_fetched = true              THEN 'available'::recordingstatus
                WHEN transcription_status = 'failed'       THEN 'permanently_missing'::recordingstatus
                ELSE 'pending'::recordingstatus
              END
            WHERE recording_status IS NULL
        """))
    else:
        op.execute(text("""
            UPDATE calls SET recording_status =
              CASE
                WHEN recording_fetched = 1             THEN 'available'
                WHEN transcription_status = 'failed'   THEN 'permanently_missing'
                ELSE 'pending'
              END
            WHERE recording_status IS NULL
        """))


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if _column_exists("calls", "recording_error"):
        op.drop_column("calls", "recording_error")

    if _column_exists("calls", "recording_status"):
        op.drop_column("calls", "recording_status")

    if is_pg and _type_exists("recordingstatus"):
        op.execute(text("DROP TYPE recordingstatus"))
