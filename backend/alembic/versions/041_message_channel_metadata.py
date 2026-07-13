"""T0.3 messages.channel_metadata (Instagram ad-attribution capture)

Stores raw ad-attribution data from Meta -- message.referral on inbound
DMs from Click-to-Instagram ads, and media.ad_id/ad_title on comments
(Phase 1). Nullable JSON, not a new table, per the Instagram module
build plan's Architecture Decision #4.

Revision ID: 041
Revises: 040
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def _column_exists(table: str, col: str) -> bool:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _column_exists("messages", "channel_metadata"):
        op.add_column(
            "messages",
            sa.Column("channel_metadata", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    if _column_exists("messages", "channel_metadata"):
        op.drop_column("messages", "channel_metadata")
