"""tenant dashboard_config column

Revision ID: 030
Revises: 029
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tenants",
        sa.Column("dashboard_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade():
    op.drop_column("tenants", "dashboard_config")
