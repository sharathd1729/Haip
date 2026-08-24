"""Persist why a drafted message got flagged needs_human.

Confirmed live gap: a 7-day query found 63 of 95 AI drafts scored above
the tenant's autonomous confidence threshold (0.78) yet only 32 actually
auto-sent -- the other 31 were held despite high confidence, meaning
needs_human=True fired without the deterministic guards zeroing
confidence (those guards force confidence=0.0 when they fire, so a
nonzero score means it was either the model's own self-reported
needs_human flag, or a fired guard whose reason was never persisted).
CONCIERGE_TOOL's reason_needs_human field already exists in the model's
own output and in the deterministic guards' log lines, but nothing ever
wrote it to the row -- so this exact "why" question is unanswerable from
the database once the log line rotates. This closes that gap.

Revision ID: 088
Revises: 087
Create Date: 2026-08-24
"""
from alembic import op
import sqlalchemy as sa

revision = "088"
down_revision = "087"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("ai_needs_human_reason", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("messages", "ai_needs_human_reason")
