"""Detailed per-lead report: route/upsell/analysis fields on Inquiry.

New extraction dimensions the report needs that nothing tracks today --
route/locations mentioned and upsell offered/accepted -- plus a synthesized
per-lead analysis paragraph (distinct from the existing 3-sentence
ai_summary). Inquiry.quoted_amount/quoted_at already exist on the model
but have no write path anywhere in the codebase (confirmed via grep) --
generate_ai_summary.py's v4 extraction starts writing them; no schema
change needed for those two.

Revision ID: 093
Revises: 092
Create Date: 2026-08-28
"""
from alembic import op
import sqlalchemy as sa

revision = "093"
down_revision = "092"
branch_labels = None
depends_on = None


def _column_exists(table: str, col: str) -> bool:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _column_exists("inquiries", "route_mentioned"):
        op.add_column("inquiries", sa.Column("route_mentioned", sa.String(255), nullable=True))
    if not _column_exists("inquiries", "upsell_offered"):
        op.add_column("inquiries", sa.Column("upsell_offered", sa.String(255), nullable=True))
    if not _column_exists("inquiries", "upsell_accepted"):
        op.add_column("inquiries", sa.Column("upsell_accepted", sa.Boolean(), nullable=True))
    if not _column_exists("inquiries", "ai_lead_analysis"):
        op.add_column("inquiries", sa.Column("ai_lead_analysis", sa.Text(), nullable=True))


def downgrade() -> None:
    for col in ("route_mentioned", "upsell_offered", "upsell_accepted", "ai_lead_analysis"):
        if _column_exists("inquiries", col):
            op.drop_column("inquiries", col)
