"""personal_access_tokens — long-lived bearer tokens for HAIP's MCP server

Backs external AI-assistant access (e.g. Perisclaw) via the MCP endpoint --
raw token shown once at creation, only a sha256 hash persisted, matching
RefreshToken's storage convention (see auth.py's token_hash usage).

Deliberately NO row-level security on this table, matching refresh_tokens
(migration 001) -- verifying an incoming PAT means looking it up by hash
BEFORE the tenant is known (that lookup is what tells us the tenant), so
an RLS policy keyed on app.tenant_id would make the row unfindable. The
unique index on token_hash plus the app-level revoked/expired checks in
token_service.py are the security boundary here, not RLS.

Revision ID: 055
Revises: 054
Create Date: 2026-07-29
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "personal_access_tokens",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False, unique=True),
        sa.Column("scopes", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_index("ix_personal_access_tokens_tenant_id", "personal_access_tokens", ["tenant_id"])
    op.create_index("ix_personal_access_tokens_user_id", "personal_access_tokens", ["user_id"])
    op.create_index("ix_personal_access_tokens_token_hash", "personal_access_tokens", ["token_hash"], unique=True)


def downgrade():
    op.drop_index("ix_personal_access_tokens_token_hash", table_name="personal_access_tokens")
    op.drop_index("ix_personal_access_tokens_user_id", table_name="personal_access_tokens")
    op.drop_index("ix_personal_access_tokens_tenant_id", table_name="personal_access_tokens")
    op.drop_table("personal_access_tokens")
