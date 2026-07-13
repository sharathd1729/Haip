"""Leads360 restructure Phase 4: inquiries.qualification_status

Default "qualified" for all existing rows -- inquiries today only ever
come from manual staff creation or call ingest, both of which imply a real
lead, so this migration changes nothing about what's visible in Leads360.
It only adds the column qualification evaluation reads/writes going
forward. See lead_qualification_service.py for the evaluation rules.

Revision ID: 045
Revises: 044
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def _column_exists(table: str, col: str) -> bool:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade():
    if not _column_exists("inquiries", "qualification_status"):
        op.add_column(
            "inquiries",
            sa.Column("qualification_status", sa.String(20), nullable=False, server_default="qualified"),
        )
    op.create_index("ix_inquiries_qualification_status", "inquiries", ["qualification_status"])


def downgrade():
    op.drop_index("ix_inquiries_qualification_status", table_name="inquiries")
    op.drop_column("inquiries", "qualification_status")
