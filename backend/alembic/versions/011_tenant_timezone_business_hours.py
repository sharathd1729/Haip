"""011 tenant timezone and business hours

B10: Per-tenant timezone (IANA) and business hours config.
Existing tenants default to Asia/Kolkata + empty business_hours.

Revision ID: 011
Revises: 010
Create Date: 2026-05-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def _col_exists(inspector, table: str, col: str) -> bool:
    return any(c["name"] == col for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    if not _col_exists(insp, "tenants", "timezone"):
        op.add_column(
            "tenants",
            sa.Column("timezone", sa.String(60), nullable=False, server_default="Asia/Kolkata"),
        )

    if not _col_exists(insp, "tenants", "business_hours"):
        op.add_column(
            "tenants",
            sa.Column("business_hours", sa.JSON(), nullable=False, server_default="{}"),
        )


def downgrade() -> None:
    op.drop_column("tenants", "timezone")
    op.drop_column("tenants", "business_hours")
