"""API usage log (SMS9 parity, Track D): one row per public API call made with an API key (method, route template,
status, duration), shown as "Recent calls" per key in Settings > Developers. Kept 30 days (webhooks.purge_old).
tenant_id + forced RLS. Idempotent (IF NOT EXISTS, guarded policy) because production runs create_all at startup.

Revision ID: 220
Revises: 219
"""
from alembic import op

revision = "220"
down_revision = "219"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS api_usage_logs (
            id           VARCHAR PRIMARY KEY,
            tenant_id    VARCHAR NOT NULL,
            api_key_id   VARCHAR NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
            method       VARCHAR(8) NOT NULL,
            path         VARCHAR(200) NOT NULL,
            status_code  INTEGER NOT NULL,
            duration_ms  INTEGER NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_api_usage_logs_key_created ON api_usage_logs (tenant_id, api_key_id, created_at)")
    op.execute("ALTER TABLE api_usage_logs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE api_usage_logs FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'api_usage_logs'
                           AND policyname = 'api_usage_logs_tenant_isolation') THEN
                CREATE POLICY api_usage_logs_tenant_isolation ON api_usage_logs
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
            END IF;
        END
        $$
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS api_usage_logs")
