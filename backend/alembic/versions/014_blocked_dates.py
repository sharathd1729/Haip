"""blocked_dates table

Revision ID: 014
Revises: 013
Create Date: 2026-05-24
"""
from alembic import op
import sqlalchemy as sa

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = inspector.get_table_names()

    if "blocked_dates" not in existing:
        op.create_table(
            "blocked_dates",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("tenant_id", sa.String(), nullable=False),
            sa.Column("property_id", sa.String(), nullable=False),
            sa.Column("blocked_from", sa.String(10), nullable=False),
            sa.Column("blocked_to", sa.String(10), nullable=False),
            sa.Column("reason", sa.String(30), nullable=True, server_default="maintenance"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True, server_default="true"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.ForeignKeyConstraint(["property_id"], ["properties.id"]),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_blocked_dates_tenant_id", "blocked_dates", ["tenant_id"])
        op.create_index("ix_blocked_dates_property_id", "blocked_dates", ["property_id"])


def downgrade():
    op.drop_index("ix_blocked_dates_property_id", table_name="blocked_dates")
    op.drop_index("ix_blocked_dates_tenant_id", table_name="blocked_dates")
    op.drop_table("blocked_dates")
