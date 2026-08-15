"""Phase 2.5 agent-accountability instrumentation (HAIP_Agent_Analytics_
Dashboard_Plan_1.md #2.5.2 / #2.5.3) -- two additive, nullable columns:

  messages.automation_outcome  -- set at automation-routing decision time
    (matched_auto_replied | matched_ai_drafted | no_match_ai_drafted |
    no_match_no_response), so an inbound message that hit neither a
    keyword rule nor the AI bot isn't a silent, unrecoverable miss.

  calls.recovered_by_call_id   -- nullable self-FK linking a missed
    inbound call to the outbound call that (maybe) followed it, so "did
    we call them back" becomes a query instead of unanswerable.

Both tables are already tenant-scoped with RLS from earlier migrations --
adding a nullable column needs no new policy.

Revision ID: 073
Revises: 072
Create Date: 2026-08-15
"""
from alembic import op
import sqlalchemy as sa

revision = "073"
down_revision = "072"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("automation_outcome", sa.String(30), nullable=True))
    op.add_column("calls", sa.Column("recovered_by_call_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_calls_recovered_by_call_id",
        "calls", "calls",
        ["recovered_by_call_id"], ["id"],
    )


def downgrade():
    op.drop_constraint("fk_calls_recovered_by_call_id", "calls", type_="foreignkey")
    op.drop_column("calls", "recovered_by_call_id")
    op.drop_column("messages", "automation_outcome")
