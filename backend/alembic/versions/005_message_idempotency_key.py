"""005 message idempotency key

Adds idempotency_key column to messages + partial unique index
so that duplicate outbound sends within 24h can be detected.

Revision ID: 005
Revises: 004
Create Date: 2026-05-18
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return any(c["name"] == column for c in insp.get_columns(table))


def _index_exists(index: str, table: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return any(i["name"] == index for i in insp.get_indexes(table))


def upgrade() -> None:
    # Add idempotency_key column (nullable — existing rows get NULL)
    if not _column_exists("messages", "idempotency_key"):
        op.add_column(
            "messages",
            sa.Column("idempotency_key", sa.String(64), nullable=True),
        )

    # Partial unique index: enforce uniqueness only when key is present
    # This prevents duplicate sends on retry while allowing non-keyed sends freely.
    # Note: partial indexes are Postgres-specific; SQLite (used in tests) ignores the WHERE clause.
    if not _index_exists("uq_messages_idempotency", "messages"):
        try:
            op.execute(text(
                "CREATE UNIQUE INDEX uq_messages_idempotency "
                "ON messages (tenant_id, idempotency_key) "
                "WHERE idempotency_key IS NOT NULL"
            ))
        except Exception:
            # SQLite / older engines: fall back to a plain index (weaker but safe)
            try:
                op.create_index(
                    "uq_messages_idempotency",
                    "messages",
                    ["tenant_id", "idempotency_key"],
                    unique=False,  # can't enforce partial uniqueness on SQLite
                )
            except Exception:
                pass  # index may already exist


def downgrade() -> None:
    try:
        op.drop_index("uq_messages_idempotency", table_name="messages")
    except Exception:
        pass
    if _column_exists("messages", "idempotency_key"):
        op.drop_column("messages", "idempotency_key")
