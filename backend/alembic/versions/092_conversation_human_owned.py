"""Conversation.human_owned -- auto-shadow once a human agent takes over.

Real gap: Conversation.ai_mode (shadow/autonomous/off) only carries the
tenant's default snapshotted at creation time -- ai_mode_service.py
deliberately ignores a per-conversation "shadow"/"autonomous" value as a
stale snapshot, not a real decision. There was no way to say "a human is
now handling this thread" and have it actually override an autonomous
tenant default. human_owned is a real, programmatically-set signal (first
outbound human send/template-send/draft-approval in the thread) that
ai_mode_service checks before falling back to the tenant default, forcing
shadow (never off -- the AI still drafts suggestions) so the bot never
auto-sends into a conversation a person is actively working.

Revision ID: 092
Revises: 091
Create Date: 2026-08-27
"""
from alembic import op
import sqlalchemy as sa

revision = "092"
down_revision = "091"
branch_labels = None
depends_on = None


def _column_exists(table: str, col: str) -> bool:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _column_exists("conversations", "human_owned"):
        op.add_column(
            "conversations",
            sa.Column("human_owned", sa.Boolean(), nullable=False, server_default="false"),
        )


def downgrade() -> None:
    if _column_exists("conversations", "human_owned"):
        op.drop_column("conversations", "human_owned")
