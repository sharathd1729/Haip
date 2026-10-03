"""Count AI scoring attempts per call so recovery can retry without looping.

Real incident (Ratha, Oct 2026): calls from 28 Sep showed ai_score_status
"failed" and older calls sat at "pending" indefinitely. judge() gives up after
3 retries ~90s apart, so any provider incident longer than that left calls
permanently "failed"; the task that re-dispatches stalled scoring
(call_recovery.py) only ever looked at "pending" -- and was never added to
the beat schedule at all. Recovery now retries "failed" calls too, which needs
a per-call attempt counter so a call that can never be scored (bad audio,
a prompt the model rejects) stops being retried instead of looping forever.

Revision ID: 108
Revises: 107
Create Date: 2026-10-04
"""
from alembic import op
import sqlalchemy as sa

revision = "108"
down_revision = "107"
branch_labels = None
depends_on = None


def _column_exists(table: str, col: str) -> bool:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _column_exists("calls", "ai_score_attempts"):
        op.add_column(
            "calls",
            sa.Column("ai_score_attempts", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    if _column_exists("calls", "ai_score_attempts"):
        op.drop_column("calls", "ai_score_attempts")
