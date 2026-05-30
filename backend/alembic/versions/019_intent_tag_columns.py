"""Phase 3: intent_tag columns on inquiries and calls

Revision ID: 019
Revises: 018
Create Date: 2026-05-30

Adds:
  - inquiries.intent_tag  VARCHAR(30) NULLABLE — normalized 10-bucket intent classification
  - calls.intent_tag      VARCHAR(30) NULLABLE — same normalization applied to call.occasion
"""
from alembic import op
import sqlalchemy as sa

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("inquiries", sa.Column("intent_tag", sa.String(30), nullable=True))
    op.add_column("calls",     sa.Column("intent_tag", sa.String(30), nullable=True))

    op.create_index("ix_inquiries_intent_tag", "inquiries", ["intent_tag"])
    op.create_index("ix_calls_intent_tag",     "calls",     ["intent_tag"])

    # RLS on Postgres (silently ignored on SQLite)
    try:
        op.execute(
            "ALTER INDEX ix_inquiries_intent_tag SET TABLESPACE pg_default"
        )
    except Exception:
        pass


def downgrade() -> None:
    op.drop_index("ix_calls_intent_tag",     table_name="calls")
    op.drop_index("ix_inquiries_intent_tag", table_name="inquiries")
    op.drop_column("calls",     "intent_tag")
    op.drop_column("inquiries", "intent_tag")
