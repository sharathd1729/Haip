"""003 add mfa_secret to users

Revision ID: 003
Revises: 002
Create Date: 2026-05-14
"""

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("mfa_secret", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "mfa_secret")
