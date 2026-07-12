"""IAM Phase 0: user signup consent columns, invitation expires_at as real timestamp

Revision ID: 034
Revises: 033
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade():
    # ── Platform-level signup consent on users ────────────────────────────────
    op.add_column("users", sa.Column("consent_transactional", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("users", sa.Column("consent_marketing", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("users", sa.Column("consent_analytics", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("users", sa.Column("consent_recorded_at", sa.DateTime(timezone=True), nullable=True))

    # ── UserInvitation.expires_at: fragile ISO string → real timestamptz ──────
    # Existing values are all `.isoformat()` output, so a direct cast is safe.
    op.execute(
        "ALTER TABLE user_invitations "
        "ALTER COLUMN expires_at TYPE TIMESTAMPTZ USING expires_at::timestamptz"
    )


def downgrade():
    op.execute(
        "ALTER TABLE user_invitations "
        "ALTER COLUMN expires_at TYPE VARCHAR(50) USING expires_at::text"
    )
    op.drop_column("users", "consent_recorded_at")
    op.drop_column("users", "consent_analytics")
    op.drop_column("users", "consent_marketing")
    op.drop_column("users", "consent_transactional")
