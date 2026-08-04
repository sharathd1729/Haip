"""Message.grounded_facts (HAIP_AI_Autonomy_Plan.md Phase 1, ticket 4)

Carries the bounded tool loop's fetched facts from draft creation through
to ai_draft_outcomes at approve/reject time -- nullable, additive, no RLS
change needed (messages already has one).

Revision ID: 059
Revises: 058
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("grounded_facts", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("messages", "grounded_facts")
