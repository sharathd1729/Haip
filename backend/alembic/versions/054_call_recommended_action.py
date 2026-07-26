"""Structured recommended_action fields on calls (M5+ WS1)

ai_next_action has always been free text with no way for the frontend to
render it as a clickable action. Adds a structured, nullable pair of
columns derived programmatically (not a new LLM call) from existing data
at scoring time -- see call_service.py::derive_recommended_action().

Revision ID: 054
Revises: 053
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("calls", sa.Column("recommended_action_type", sa.String(30), nullable=True))
    op.add_column("calls", sa.Column("recommended_action_target_id", sa.String(), nullable=True))


def downgrade():
    op.drop_column("calls", "recommended_action_target_id")
    op.drop_column("calls", "recommended_action_type")
