"""HAIP Calls app, step 1 (docs/MOBILE_CALL_TRACKING_SPEC.md): mobile_devices.

A staff phone running the Calls app. tenant_id + forced row-level security. The app authenticates with a per-device token;
only its SHA-256 is stored. A device request has no tenant yet, so the token lookup goes through a SECURITY DEFINER
function that resolves a hash to the device id and tenant only (same pattern as api_key_lookup, migration 112).

No calls schema change: calls.ivr_provider is a plain VARCHAR(50), so the new value "mobile_app" needs no enum/CHECK edit.
Idempotent (IF NOT EXISTS, guarded policy, CREATE OR REPLACE) because production runs create_all at startup.

Revision ID: 202
Revises: 201
"""
from alembic import op

revision = "202"
down_revision = "201"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS mobile_devices (
            id              VARCHAR PRIMARY KEY,
            tenant_id       VARCHAR NOT NULL REFERENCES tenants(id),
            user_id         VARCHAR NOT NULL REFERENCES users(id),
            device_id       VARCHAR(100) NOT NULL,
            model           VARCHAR(100),
            android_version VARCHAR(20),
            app_version     VARCHAR(20),
            token_hash      VARCHAR(64) NOT NULL,
            last_seen_at    TIMESTAMPTZ,
            settings        JSON NOT NULL DEFAULT '{}',
            revoked_at      TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_mobile_devices_token_hash UNIQUE (token_hash),
            CONSTRAINT uq_mobile_devices_tenant_device UNIQUE (tenant_id, device_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_mobile_devices_tenant_id ON mobile_devices (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_mobile_devices_user_id ON mobile_devices (user_id)")
    op.execute("ALTER TABLE mobile_devices ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE mobile_devices FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'mobile_devices' AND policyname = 'mobile_devices_tenant_isolation'
            ) THEN
                CREATE POLICY mobile_devices_tenant_isolation ON mobile_devices
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
            END IF;
        END
        $$
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION mobile_device_lookup(p_hash text)
        RETURNS TABLE (device_pk text, tenant_id text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
        $$ SELECT id::text, tenant_id::text FROM mobile_devices WHERE token_hash = p_hash LIMIT 1 $$
    """)


def downgrade():
    op.execute("DROP FUNCTION IF EXISTS mobile_device_lookup(text)")
    op.execute("DROP TABLE IF EXISTS mobile_devices")
