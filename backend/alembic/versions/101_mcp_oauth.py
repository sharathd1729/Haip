"""OAuth 2.1 for the MCP connector -- oauth_clients + oauth_grants

Claude.ai / Claude Desktop connectors and ChatGPT connectors accept only
OAuth (or no auth) for remote MCP servers -- there is nowhere to paste a
personal access token. These two tables back an authorization server built
into the existing API (HAIP_MCP_Connector_Plan.md section 8).

oauth_clients is global: Dynamic Client Registration is anonymous and
happens before any user or tenant is involved.

oauth_grants carries tenant_id but deliberately NO row-level security,
matching personal_access_tokens (055) and refresh_tokens (001): an incoming
bearer token is looked up by hash BEFORE the tenant is known, so an RLS
policy keyed on app.tenant_id would make the row unfindable. The unique
hash indexes plus revoked/expiry checks in oauth_service are the boundary.

Revision ID: 101
Revises: 100
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "101"
down_revision = "100"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("client_name", sa.String(200), nullable=False),
        sa.Column("redirect_uris", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column("token_endpoint_auth_method", sa.String(40), nullable=False, server_default="none"),
        sa.Column("client_secret_hash", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "oauth_grants",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_id", sa.String(), sa.ForeignKey("oauth_clients.id"), nullable=False),
        sa.Column("scopes", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column("resource", sa.String(500), nullable=True),
        sa.Column("code_hash", sa.String(255), nullable=True),
        sa.Column("code_challenge", sa.String(200), nullable=True),
        sa.Column("redirect_uri", sa.String(2000), nullable=True),
        sa.Column("code_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("code_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("access_token_hash", sa.String(255), nullable=True),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_token_hash", sa.String(255), nullable=True),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_oauth_grants_tenant_id", "oauth_grants", ["tenant_id"])
    op.create_index("ix_oauth_grants_user_id", "oauth_grants", ["user_id"])
    op.create_index("ix_oauth_grants_client_id", "oauth_grants", ["client_id"])
    op.create_index("ix_oauth_grants_code_hash", "oauth_grants", ["code_hash"], unique=True)
    op.create_index("ix_oauth_grants_access_token_hash", "oauth_grants", ["access_token_hash"], unique=True)
    op.create_index("ix_oauth_grants_refresh_token_hash", "oauth_grants", ["refresh_token_hash"], unique=True)


def downgrade():
    for ix in (
        "ix_oauth_grants_refresh_token_hash", "ix_oauth_grants_access_token_hash",
        "ix_oauth_grants_code_hash", "ix_oauth_grants_client_id",
        "ix_oauth_grants_user_id", "ix_oauth_grants_tenant_id",
    ):
        op.drop_index(ix, table_name="oauth_grants")
    op.drop_table("oauth_grants")
    op.drop_table("oauth_clients")
