"""Conversation source tag -- distinguishes the personal WhatsApp bridge
(whatsmeow, unofficial) from the official channel it shares a ChannelType
with. `channel="whatsapp"` alone can't tell an official Cloud API thread
apart from a personal-bridge one, but they need different treatment:
personal-bridge conversations don't have a WhatsApp 24h service window
(that's a Cloud API concept) and, per product decision, stay out of the
main Inbox for now -- shown in their own filtered view instead.

NULL = existing behavior for every current conversation (official
WhatsApp, Instagram, voice, etc.) -- purely additive.

Revision ID: 097
Revises: 096
Create Date: 2026-09-01
"""
from alembic import op
import sqlalchemy as sa

revision = "097"
down_revision = "096"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    conn = op.get_bind()
    return column in [c["name"] for c in sa.inspect(conn).get_columns(table)]


def upgrade() -> None:
    if not _has_column("conversations", "source"):
        op.add_column("conversations", sa.Column("source", sa.String(30), nullable=True))


def downgrade() -> None:
    if _has_column("conversations", "source"):
        op.drop_column("conversations", "source")
