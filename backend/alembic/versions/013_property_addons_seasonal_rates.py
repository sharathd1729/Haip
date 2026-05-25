"""property_addons and seasonal_rates tables

Revision ID: 013
Revises: 012
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = inspector.get_table_names()

    if "property_addons" not in existing:
        op.create_table(
            "property_addons",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
            sa.Column("property_id", sa.String(), sa.ForeignKey("properties.id"), nullable=False, index=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("category", sa.String(50), server_default="experience"),
            sa.Column("price", sa.Numeric(10, 2), nullable=False),
            sa.Column("price_type", sa.String(20), server_default="per_stay"),
            sa.Column("currency", sa.String(3), server_default="INR"),
            sa.Column("is_active", sa.Boolean(), server_default="true"),
            sa.Column("sort_order", sa.Integer(), server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        )

    if "seasonal_rates" not in existing:
        op.create_table(
            "seasonal_rates",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
            sa.Column("property_id", sa.String(), sa.ForeignKey("properties.id"), nullable=False, index=True),
            sa.Column("name", sa.String(100), nullable=False),
            sa.Column("date_from", sa.String(10), nullable=False),
            sa.Column("date_to", sa.String(10), nullable=False),
            sa.Column("price_per_night", sa.Numeric(10, 2), nullable=False),
            sa.Column("min_nights", sa.Integer(), server_default="1"),
            sa.Column("currency", sa.String(3), server_default="INR"),
            sa.Column("priority", sa.Integer(), server_default="0"),
            sa.Column("is_active", sa.Boolean(), server_default="true"),
            sa.Column("occupancy_pricing", sa.JSON(), server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        )


def downgrade():
    op.drop_table("seasonal_rates")
    op.drop_table("property_addons")
