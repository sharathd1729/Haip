"""tenant pipeline_config column

Revision ID: 028
Revises: 027
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tenants",
        sa.Column("pipeline_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade():
    op.drop_column("tenants", "pipeline_config")
