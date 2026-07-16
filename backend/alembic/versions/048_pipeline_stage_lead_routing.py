"""Leads360: pipeline_stages category + auto-create routing flags

Adds category (valid/invalid/marketing, for lead-counting) and
is_valid_lead_entry / is_collab_entry (routing targets for chat-based
lead auto-creation) to pipeline_stages. Additive, nullable/defaulted --
existing stages are unaffected until a tenant explicitly tags them via
the Pipeline Settings UI.

Revision ID: 048
Revises: 047
Create Date: 2026-07-16
"""
from alembic import op
import sqlalchemy as sa

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def _column_exists(table: str, col: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade():
    if not _column_exists("pipeline_stages", "category"):
        op.add_column("pipeline_stages", sa.Column("category", sa.String(20), nullable=True))
    if not _column_exists("pipeline_stages", "is_valid_lead_entry"):
        op.add_column("pipeline_stages", sa.Column("is_valid_lead_entry", sa.Boolean(), nullable=False, server_default="false"))
    if not _column_exists("pipeline_stages", "is_collab_entry"):
        op.add_column("pipeline_stages", sa.Column("is_collab_entry", sa.Boolean(), nullable=False, server_default="false"))


def downgrade():
    if _column_exists("pipeline_stages", "is_collab_entry"):
        op.drop_column("pipeline_stages", "is_collab_entry")
    if _column_exists("pipeline_stages", "is_valid_lead_entry"):
        op.drop_column("pipeline_stages", "is_valid_lead_entry")
    if _column_exists("pipeline_stages", "category"):
        op.drop_column("pipeline_stages", "category")
