"""AI Executive E4 (3 Nov 2026): what it learned per detector and workspace (services/chief/tuning.py).

New table only; nothing existing is altered. tenant_id NOT NULL and, on PostgreSQL, forced row-level security:
  * chief_detector_tuning      one row per (tenant, detector code): decision + outcome counts, the threshold step on the
                               detector's ladder, mute, autopilot offered / opted in (by which owner)
CREATE TABLE / INDEX IF NOT EXISTS and a guarded policy: idempotent (prod also runs create_all).

Revision ID: 187
Revises: 186
"""

from alembic import op

revision = "187"
down_revision = "186"
branch_labels = None
depends_on = None

TABLE = "chief_detector_tuning"
COLUMNS = """
    id                    VARCHAR PRIMARY KEY,
    tenant_id             VARCHAR NOT NULL REFERENCES tenants(id),
    code                  VARCHAR(10) NOT NULL,
    step                  INTEGER NOT NULL DEFAULT 1,
    approved              INTEGER NOT NULL DEFAULT 0,
    rejected              INTEGER NOT NULL DEFAULT 0,
    dismissed             INTEGER NOT NULL DEFAULT 0,
    improved              INTEGER NOT NULL DEFAULT 0,
    no_change             INTEGER NOT NULL DEFAULT 0,
    worse                 INTEGER NOT NULL DEFAULT 0,
    rejections_in_row     INTEGER NOT NULL DEFAULT 0,
    wins_in_row           INTEGER NOT NULL DEFAULT 0,
    muted_until           TIMESTAMP WITH TIME ZONE,
    last_reason           TEXT,
    autopilot_offered_at  TIMESTAMP WITH TIME ZONE,
    autopilot_by          VARCHAR REFERENCES users(id),
    autopilot_at          TIMESTAMP WITH TIME ZONE,
    created_at            TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
"""


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"CREATE TABLE IF NOT EXISTS {TABLE} ({COLUMNS})")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_tenant_id ON {TABLE} (tenant_id)")
    op.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{TABLE}_code ON {TABLE} (tenant_id, code)")
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
