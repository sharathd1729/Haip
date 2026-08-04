"""Message.suggested_actions (HAIP Inbox prototype-wiring plan, ticket 4)

Carries a structured one-click action (e.g. send_quote) alongside a grounded
draft, so the inbox thread can render an inline AIRecommendationCard next to
the message -- the prototype's ai_card message type, backed by real data.
Additive, nullable, no RLS change needed (messages already has one).

Revision ID: 061
Revises: 060
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "061"
down_revision = "060"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("suggested_actions", postgresql.JSONB(), nullable=True))


def downgrade():
    op.drop_column("messages", "suggested_actions")
