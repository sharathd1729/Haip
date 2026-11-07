"""Calendar sync: a person's "Hold only this villa" answer for a shared-calendar event that named no unit (7 Nov 2026).

New table only; nothing existing is altered. tenant_id NOT NULL and, on PostgreSQL, forced row-level security:
  * ical_event_assignments   one row per (tenant, feed, event key): the unit (property) the event is for
CREATE TABLE / INDEX IF NOT EXISTS and a guarded policy: idempotent (prod also runs create_all).

Revision ID: 188
Revises: 187
"""

from alembic import op

revision = "188"
down_revision = "187"
branch_labels = None
depends_on = None

TABLE = "ical_event_assignments"
COLUMNS = """
    id           VARCHAR PRIMARY KEY,
    tenant_id    VARCHAR NOT NULL REFERENCES tenants(id),
    feed_id      VARCHAR NOT NULL,
    event_key    VARCHAR(300) NOT NULL,
    property_id  VARCHAR NOT NULL,
    assigned_by  VARCHAR,
    created_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
"""


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"CREATE TABLE IF NOT EXISTS {TABLE} ({COLUMNS})")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_tenant_id ON {TABLE} (tenant_id)")
    op.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS uq_ical_event_assignment ON {TABLE} (tenant_id, feed_id, event_key)")
    if postgres:
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
