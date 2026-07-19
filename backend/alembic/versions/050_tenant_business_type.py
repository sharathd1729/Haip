"""tenants.business_type — signup-chosen vertical driving per-type dashboards

Additive, nullable. Values: caravan / villa_resort / homestay / hotel.
Existing tenants stay NULL (nothing hidden) until manually backfilled
post-deploy (Ratha -> caravan, Jade -> villa_resort).

Revision ID: 050
Revises: 049
Create Date: 2026-07-18
"""
from alembic import op
import sqlalchemy as sa

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def _column_exists(table: str, col: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade():
    if not _column_exists("tenants", "business_type"):
        op.add_column("tenants", sa.Column("business_type", sa.String(30), nullable=True))


def downgrade():
    if _column_exists("tenants", "business_type"):
        op.drop_column("tenants", "business_type")
