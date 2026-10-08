"""Outbound webhooks for the public API

Revision ID: 113
Revises: 112
Create Date: 2026-10-09
"""
from alembic import op

revision = "113"
down_revision = "112"
branch_labels = None
depends_on = None

_TABLES = ("webhook_endpoints", "webhook_deliveries")


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS webhook_endpoints (
            id                   VARCHAR PRIMARY KEY,
            tenant_id            VARCHAR NOT NULL,
            url                  VARCHAR(500) NOT NULL,
            description          VARCHAR(200),
            secret_enc           BYTEA NOT NULL,
            events               JSON NOT NULL DEFAULT '[]',
            is_active            BOOLEAN NOT NULL DEFAULT true,
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            disabled_reason      VARCHAR(200),
            last_success_at      TIMESTAMPTZ,
            last_failure_at      TIMESTAMPTZ,
            created_by           VARCHAR REFERENCES users(id),
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS webhook_deliveries (
            id               VARCHAR PRIMARY KEY,
            tenant_id        VARCHAR NOT NULL,
            endpoint_id      VARCHAR NOT NULL REFERENCES webhook_endpoints(id) ON DELETE CASCADE,
            event_id         VARCHAR(40) NOT NULL,
            event_type       VARCHAR(50) NOT NULL,
            payload          JSON NOT NULL,
            status           VARCHAR(10) NOT NULL DEFAULT 'pending',
            attempts         INTEGER NOT NULL DEFAULT 0,
            next_attempt_at  TIMESTAMPTZ,
            response_status  INTEGER,
            last_error       VARCHAR(500),
            delivered_at     TIMESTAMPTZ,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_webhook_deliveries_due ON webhook_deliveries (status, next_attempt_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_webhook_deliveries_endpoint_id ON webhook_deliveries (endpoint_id)")
    for t in _TABLES:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{t}_tenant_id ON {t} (tenant_id)")
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = '{t}' AND policyname = '{t}_tenant_isolation'
                ) THEN
                    CREATE POLICY {t}_tenant_isolation ON {t}
                    USING (tenant_id = current_setting('app.tenant_id', true)::text);
                END IF;
            END
            $$
        """)


def downgrade():
    for t in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t}")
