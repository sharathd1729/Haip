"""012 user digest_opt_in column

A7: Per-user opt-in for daily owner digest.

Revision ID: 012
Revises: 011
Create Date: 2026-05-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def _col_exists(inspector, table: str, col: str) -> bool:
    return any(c["name"] == col for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)

    if not _col_exists(insp, "users", "digest_opt_in"):
        op.add_column(
            "users",
            sa.Column("digest_opt_in", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )


def downgrade() -> None:
    op.drop_column("users", "digest_opt_in")
