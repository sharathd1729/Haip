"""Website phase 2 (measurement): Meta Pixel / Conversions API / GA4 per site, and the server-side event log.

  * sites.tracking JSON          -- public ids only: {pixel_id, ga4_id, capi_enabled, capi_test_code}
  * sites.capi_token_enc TEXT    -- the owner's Conversions API token, Fernet-encrypted (core.encryption), never returned
  * website_events (new, tenant_id + forced RLS) -- one row per Lead / InitiateCheckout / Purchase a website visitor
    caused; event_id is shared with the browser pixel so Meta counts it once. Sent by beat website.send_events.
Idempotent (IF NOT EXISTS, guarded policy): production runs create_all at startup.

Revision ID: 183
Revises: 182
"""

from alembic import op

revision = "183"
down_revision = "182"
branch_labels = None
depends_on = None

_TABLE = "website_events"
_COLS = """
    id                VARCHAR PRIMARY KEY,
    tenant_id         VARCHAR NOT NULL REFERENCES tenants(id),
    site_id           VARCHAR NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    event_name        VARCHAR(30) NOT NULL,
    event_id          VARCHAR(80) NOT NULL,
    guest_id          VARCHAR,
    inquiry_id        VARCHAR,
    hold_id           VARCHAR,
    value             NUMERIC(12, 2),
    currency          VARCHAR(3),
    source_url        VARCHAR(500),
    client_user_agent VARCHAR(300),
    fbp               VARCHAR(200),
    fbc               VARCHAR(200),
    status            VARCHAR(12) NOT NULL DEFAULT 'pending',
    reason            VARCHAR(300),
    tries             INTEGER NOT NULL DEFAULT 0,
    sent_at           TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_website_events_event UNIQUE (tenant_id, event_id)
"""


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
        op.execute("ALTER TABLE sites ADD COLUMN IF NOT EXISTS tracking JSON")
        op.execute("ALTER TABLE sites ADD COLUMN IF NOT EXISTS capi_token_enc TEXT")
    else:
        existing = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(sites)")}
        for name, kind in (("tracking", "JSON"), ("capi_token_enc", "TEXT")):
            if name not in existing:
                op.execute(f"ALTER TABLE sites ADD COLUMN {name} {kind}")
    op.execute(f"CREATE TABLE IF NOT EXISTS {_TABLE} ({_COLS})")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_tenant_id ON {_TABLE} (tenant_id)")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_status ON {_TABLE} (tenant_id, status)")
    if postgres:
        op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies WHERE tablename = '{_TABLE}' AND policyname = '{_TABLE}_tenant_isolation'
                ) THEN
                    CREATE POLICY {_TABLE}_tenant_isolation ON {_TABLE}
                    USING (tenant_id = current_setting('app.tenant_id', true)::text);
                END IF;
            END
            $$
        """)


def downgrade():
    op.execute(f"DROP TABLE IF EXISTS {_TABLE}")
    op.execute("ALTER TABLE sites DROP COLUMN IF EXISTS capi_token_enc")
    op.execute("ALTER TABLE sites DROP COLUMN IF EXISTS tracking")
