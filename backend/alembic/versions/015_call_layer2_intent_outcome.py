"""call layer2 intent outcome fields

Revision ID: 015
Revises: 014
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("calls", sa.Column("occasion", sa.String(50), nullable=True))
    op.add_column("calls", sa.Column("budget_signal", sa.String(100), nullable=True))
    op.add_column("calls", sa.Column("decision_stage", sa.String(50), nullable=True))
    op.add_column("calls", sa.Column("competitor_mentioned", sa.String(255), nullable=True))
    op.add_column("calls", sa.Column("conversion_probability", sa.Integer(), nullable=True))
    op.add_column("calls", sa.Column("lost_reason", sa.String(100), nullable=True))


def downgrade():
    op.drop_column("calls", "lost_reason")
    op.drop_column("calls", "conversion_probability")
    op.drop_column("calls", "competitor_mentioned")
    op.drop_column("calls", "decision_stage")
    op.drop_column("calls", "budget_signal")
    op.drop_column("calls", "occasion")
