"""iCal calendar links (Airbnb / Booking.com / Google ...)

New table ical_feeds with tenant_id and row-level security. Production builds
tables with create_all at API startup, which adds no RLS -- so this creates the
table itself if missing and then always enables RLS and the policy. Every
statement is idempotent.

Revision ID: 109
Revises: 108
Create Date: 2026-10-07
"""
from alembic import op

revision = "109"
down_revision = "108"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS ical_feeds (
            id                VARCHAR PRIMARY KEY,
            tenant_id         VARCHAR NOT NULL,
            property_id       VARCHAR NOT NULL,
            name              VARCHAR(80) NOT NULL,
            import_url_enc    BYTEA,
            export_token      VARCHAR(64) NOT NULL,
            is_active         BOOLEAN NOT NULL DEFAULT true,
            last_synced_at    TIMESTAMPTZ,
            last_status       VARCHAR(20),
            last_error        VARCHAR(500),
            last_event_count  INTEGER,
            last_conflicts    INTEGER,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ical_feed_export_token UNIQUE (export_token)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ical_feeds_tenant_id ON ical_feeds (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ical_feeds_property_id ON ical_feeds (property_id)")

    op.execute("ALTER TABLE ical_feeds ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ical_feeds FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'ical_feeds' AND policyname = 'ical_feeds_tenant_isolation'
            ) THEN
                CREATE POLICY ical_feeds_tenant_isolation ON ical_feeds
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
            END IF;
        END
        $$
    """)

    # The public export URL is fetched by Airbnb/Google with no login, so there
    # is no tenant to scope by. This function resolves a token to its tenant
    # (and nothing else) under the definer's rights; the caller then sets the
    # tenant context and reads the feed through the normal RLS policy.
    op.execute("""
        CREATE OR REPLACE FUNCTION ical_feed_tenant(p_token text) RETURNS text
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
        $$ SELECT tenant_id FROM ical_feeds WHERE export_token = p_token AND is_active LIMIT 1 $$
    """)


def downgrade():
    op.execute("DROP FUNCTION IF EXISTS ical_feed_tenant(text)")
    op.execute("DROP TABLE IF EXISTS ical_feeds")
