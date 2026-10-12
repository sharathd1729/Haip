"""Shared calendars: which vehicle an event belongs to, and the booking details read from each imported event

Two NEW tables (no existing table is altered, so code and database can be deployed in either order):
  * ical_feed_vehicles  -- per calendar link, name keywords for each vehicle (property);
  * ical_event_details  -- title, guest / phone / destination / package / amounts read from an imported event, one row
                           per imported block.
Both carry tenant_id and row-level security. create_all at API startup creates the tables but not the policies, so every
statement is idempotent and safe whichever of the two gets there first (same pattern as migration 116).

Numbering: follows 119; 118 stays reserved for the proposed RLS migration (see 119's note).

Revision ID: 120
Revises: 119
Create Date: 2026-10-12
"""
from alembic import op

revision = "120"
down_revision = "119"
branch_labels = None
depends_on = None

TABLES = ("ical_feed_vehicles", "ical_event_details")


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS ical_feed_vehicles (
            id           VARCHAR PRIMARY KEY,
            tenant_id    VARCHAR NOT NULL,
            feed_id      VARCHAR NOT NULL,
            property_id  VARCHAR NOT NULL,
            keywords     JSON NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ical_feed_vehicle UNIQUE (feed_id, property_id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS ical_event_details (
            id               VARCHAR PRIMARY KEY,
            tenant_id        VARCHAR NOT NULL,
            blocked_date_id  VARCHAR NOT NULL,
            feed_id          VARCHAR NOT NULL,
            event_uid        VARCHAR(255) NOT NULL,
            title            VARCHAR(255),
            details          JSON,
            dates_source     VARCHAR(12) NOT NULL DEFAULT 'event',
            needs_vehicle    BOOLEAN NOT NULL DEFAULT false,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ical_event_details_block UNIQUE (blocked_date_id)
        )
    """)
    for table in TABLES:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ical_feed_vehicles_feed_id ON ical_feed_vehicles (feed_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ical_feed_vehicles_property_id ON ical_feed_vehicles (property_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ical_event_details_feed_id ON ical_event_details (feed_id)")

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = '{table}' AND policyname = '{table}_tenant_isolation'
                ) THEN
                    CREATE POLICY {table}_tenant_isolation ON {table}
                    USING (tenant_id = current_setting('app.tenant_id', true)::text);
                END IF;
            END
            $$
        """)


def downgrade():
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")
