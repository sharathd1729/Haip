"""Yaad calendar (personal workspaces, services/personal_calendar.py): yaad_events.

An event is the person's own: made by hand (status accepted) or suggested from a plan said on a call (status suggested,
source_key = one per call plan, so a re-read never duplicates it; dismissed suggestions stay dismissed; source_ref = {at, quote}: the moment on the call the plan was said). Notes / remarks and
people (stakeholders) are editable. google = the person chose to have it in Google Calendar; google_event_id is the copy's
id once pushed (sync is a later step). tenant_id + forced RLS. Idempotent: production runs create_all at startup.

Revision ID: 206
Revises: 205
"""

from alembic import op

revision = "206"
down_revision = "205"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS yaad_events (
            id               VARCHAR PRIMARY KEY,
            tenant_id        VARCHAR NOT NULL REFERENCES tenants(id),
            title            VARCHAR(160) NOT NULL,
            day              DATE NOT NULL,
            start_time       VARCHAR(5),
            place            VARCHAR(160) NOT NULL DEFAULT '',
            notes            TEXT NOT NULL DEFAULT '',
            people           JSON NOT NULL DEFAULT '[]',
            status           VARCHAR(12) NOT NULL DEFAULT 'accepted',
            call_id          VARCHAR REFERENCES calls(id) ON DELETE SET NULL,
            source_key       VARCHAR(64),
            source_ref       JSON,
            google           BOOLEAN NOT NULL DEFAULT false,
            google_event_id  VARCHAR(255),
            google_synced_at TIMESTAMPTZ,
            google_error     VARCHAR(300),
            created_by       VARCHAR REFERENCES users(id),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_yaad_events_tenant_source UNIQUE (tenant_id, source_key)
        )
    """)
    op.execute("ALTER TABLE yaad_events ADD COLUMN IF NOT EXISTS source_ref JSON")  # a local db made before it
    op.execute("CREATE INDEX IF NOT EXISTS ix_yaad_events_tenant_day ON yaad_events (tenant_id, day)")
    op.execute("ALTER TABLE yaad_events ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE yaad_events FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'yaad_events'
                           AND policyname = 'yaad_events_tenant_isolation') THEN
                CREATE POLICY yaad_events_tenant_isolation ON yaad_events
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
            END IF;
        END
        $$
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS yaad_events")
