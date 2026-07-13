"""T3.2 tenants.ig_ai_mode_default + ig_ai_confidence_threshold

Per-tenant Instagram AI concierge defaults, so Ratha and Jade can carry
different risk tolerance without a code change. Replaces the hardcoded
CONFIDENCE_THRESHOLD = 0.78 constant in concierge_draft.py.

Revision ID: 042
Revises: 041
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa

revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def _column_exists(table: str, col: str) -> bool:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _column_exists("tenants", "ig_ai_mode_default"):
        op.add_column(
            "tenants",
            sa.Column("ig_ai_mode_default", sa.String(20), nullable=False, server_default="shadow"),
        )
    if not _column_exists("tenants", "ig_ai_confidence_threshold"):
        op.add_column(
            "tenants",
            sa.Column("ig_ai_confidence_threshold", sa.Float(), nullable=False, server_default="0.78"),
        )


def downgrade() -> None:
    if _column_exists("tenants", "ig_ai_confidence_threshold"):
        op.drop_column("tenants", "ig_ai_confidence_threshold")
    if _column_exists("tenants", "ig_ai_mode_default"):
        op.drop_column("tenants", "ig_ai_mode_default")
