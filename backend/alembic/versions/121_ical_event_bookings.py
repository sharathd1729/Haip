"""Link a Google Calendar event to the booking made from it.

A shared calendar (migration 120) can now turn a complete event into a real booking. This table remembers which booking an
event produced, so editing or deleting the event updates or cancels that booking instead of creating a second one. ``locked`` means the CRM is in charge: someone edited the booking
(or it already existed before the event was seen), so the calendar stops changing it.

New table only (nothing altered), idempotent, tenant isolation policy like 120.

Revision ID: 121
Revises: 120
"""
from alembic import op

revision = "121"
down_revision = "120"
branch_labels = None
depends_on = None

TABLE = "ical_event_bookings"


def upgrade():
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id          VARCHAR PRIMARY KEY,
            tenant_id   VARCHAR NOT NULL,
            feed_id     VARCHAR NOT NULL,
            event_key   VARCHAR(300) NOT NULL,
            stay_id     VARCHAR NOT NULL,
            payment_id  VARCHAR,
            locked      BOOLEAN NOT NULL DEFAULT false,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ical_event_booking UNIQUE (feed_id, event_key)
        )
    """)
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_tenant_id ON {TABLE} (tenant_id)")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_stay_id ON {TABLE} (stay_id)")
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies WHERE tablename = '{TABLE}' AND policyname = '{TABLE}_tenant_isolation'
            ) THEN
                CREATE POLICY {TABLE}_tenant_isolation ON {TABLE}
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
            END IF;
        END
        $$
    """)


def downgrade():
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
