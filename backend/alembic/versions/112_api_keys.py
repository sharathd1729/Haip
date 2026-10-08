"""API keys for the public API

New table api_keys (tenant_id + RLS). A request carrying an API key has no tenant
yet, so lookup goes through a SECURITY DEFINER function that resolves a key hash
to its key id and tenant (and nothing else); the caller then sets the tenant
context and reads the row through the normal RLS policy.

Revision ID: 112
Revises: 111
Create Date: 2026-10-09
"""
from alembic import op

revision = "112"
down_revision = "111"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id           VARCHAR PRIMARY KEY,
            tenant_id    VARCHAR NOT NULL,
            name         VARCHAR(100) NOT NULL,
            prefix       VARCHAR(20) NOT NULL,
            key_hash     VARCHAR(64) NOT NULL,
            scopes       JSON NOT NULL DEFAULT '[]',
            created_by   VARCHAR REFERENCES users(id),
            last_used_at TIMESTAMPTZ,
            expires_at   TIMESTAMPTZ,
            revoked_at   TIMESTAMPTZ,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_api_keys_key_hash UNIQUE (key_hash)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_api_keys_tenant_id ON api_keys (tenant_id)")
    op.execute("ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE api_keys FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'api_keys' AND policyname = 'api_keys_tenant_isolation'
            ) THEN
                CREATE POLICY api_keys_tenant_isolation ON api_keys
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
            END IF;
        END
        $$
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION api_key_lookup(p_hash text)
        RETURNS TABLE (key_id text, tenant_id text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
        $$ SELECT id::text, tenant_id::text FROM api_keys WHERE key_hash = p_hash LIMIT 1 $$
    """)


def downgrade():
    op.execute("DROP FUNCTION IF EXISTS api_key_lookup(text)")
    op.execute("DROP TABLE IF EXISTS api_keys")
