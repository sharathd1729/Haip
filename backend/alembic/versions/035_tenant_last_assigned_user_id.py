"""tenants.last_assigned_user_id (K14 round-robin assignment state)

app/models/tenant.py has always declared this column, but it was added
directly to the live database and never captured as a migration — schema
drift discovered when building a fresh database from migration history.

Revision ID: 035
Revises: 034
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def _column_exists(table: str, col: str) -> bool:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _column_exists("tenants", "last_assigned_user_id"):
        op.add_column(
            "tenants",
            sa.Column("last_assigned_user_id", sa.String(), nullable=True),
        )


def downgrade() -> None:
    if _column_exists("tenants", "last_assigned_user_id"):
        op.drop_column("tenants", "last_assigned_user_id")
