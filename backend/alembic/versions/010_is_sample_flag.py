"""010 is_sample flag on guests, conversations, calls

O2: Sample-data toggle for new-tenant activation.
Rows with is_sample=True are auto-wiped on first real inbound message.

Revision ID: 010
Revises: 009
Create Date: 2026-05-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def _col_exists(inspector, table: str, col: str) -> bool:
    return any(c["name"] == col for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    if not _col_exists(insp, "guests", "is_sample"):
        op.add_column(
            "guests",
            sa.Column("is_sample", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
        op.create_index("ix_guests_is_sample", "guests", ["is_sample"])

    if not _col_exists(insp, "conversations", "is_sample"):
        op.add_column(
            "conversations",
            sa.Column("is_sample", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
        op.create_index("ix_conversations_is_sample", "conversations", ["is_sample"])

    if not _col_exists(insp, "messages", "is_sample"):
        op.add_column(
            "messages",
            sa.Column("is_sample", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
        op.create_index("ix_messages_is_sample", "messages", ["is_sample"])

    if not _col_exists(insp, "calls", "is_sample"):
        op.add_column(
            "calls",
            sa.Column("is_sample", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )
        op.create_index("ix_calls_is_sample", "calls", ["is_sample"])


def downgrade() -> None:
    op.drop_index("ix_guests_is_sample", table_name="guests")
    op.drop_column("guests", "is_sample")

    op.drop_index("ix_conversations_is_sample", table_name="conversations")
    op.drop_column("conversations", "is_sample")

    op.drop_index("ix_messages_is_sample", table_name="messages")
    op.drop_column("messages", "is_sample")

    op.drop_index("ix_calls_is_sample", table_name="calls")
    op.drop_column("calls", "is_sample")
