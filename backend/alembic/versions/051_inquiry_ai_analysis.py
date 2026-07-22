"""inquiries.ai_analysis — structured AI analysis JSON

Additive, nullable. Written by the generate_ai_summary Celery task
(prompt leads360-summary-v2) alongside the prose ai_summary:
{intent, sentiment, objection, reply_urgency, next_action}.
Older leads stay NULL until their summary next regenerates.

Revision ID: 051
Revises: 050
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def _column_exists(table: str, col: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade():
    if not _column_exists("inquiries", "ai_analysis"):
        op.add_column("inquiries", sa.Column("ai_analysis", sa.JSON(), nullable=True))


def downgrade():
    if _column_exists("inquiries", "ai_analysis"):
        op.drop_column("inquiries", "ai_analysis")
