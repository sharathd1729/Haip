"""009 message: is_internal, replied_to_message_id, scheduled_for

W24: internal notes
W5: reply-to-message
W4: scheduled send

Revision ID: 009
Revises: 008
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def _col(table: str, col: str) -> bool:
    bind = op.get_bind()
    return col in {c["name"] for c in inspect(bind).get_columns(table)}


def upgrade():
    if not _col("messages", "is_internal"):
        op.add_column("messages", sa.Column("is_internal", sa.Boolean(), nullable=False, server_default="false"))
    if not _col("messages", "replied_to_message_id"):
        op.add_column("messages", sa.Column("replied_to_message_id", sa.String(), nullable=True))
    if not _col("messages", "scheduled_for"):
        op.add_column("messages", sa.Column("scheduled_for", sa.String(64), nullable=True))


def downgrade():
    for col in ("scheduled_for", "replied_to_message_id", "is_internal"):
        if _col("messages", col):
            op.drop_column("messages", col)
