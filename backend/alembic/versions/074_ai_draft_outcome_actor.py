"""Phase 2.5 agent-accountability instrumentation (HAIP_Agent_Analytics_
Dashboard_Plan_1.md #2.5.4): ai_draft_outcomes.actor_user_id -- the agent
who approved/rejected an AI draft. Previously uncaptured: approve_ai_draft
set Message.sender_id on approve only, reject_ai_draft recorded no actor
at all. Additive, nullable -- no backfill for existing rows (their actor
is genuinely unknown, not worth guessing).

Revision ID: 074
Revises: 073
Create Date: 2026-08-15
"""
from alembic import op
import sqlalchemy as sa

revision = "074"
down_revision = "073"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ai_draft_outcomes", sa.Column("actor_user_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_ai_draft_outcomes_actor_user_id",
        "ai_draft_outcomes", "users",
        ["actor_user_id"], ["id"],
    )


def downgrade():
    op.drop_constraint("fk_ai_draft_outcomes_actor_user_id", "ai_draft_outcomes", type_="foreignkey")
    op.drop_column("ai_draft_outcomes", "actor_user_id")
