"""Marketing agency M2b: jobs sent to outside creative tools (Canva designs, Higgsfield videos).

New table only; tenant_id NOT NULL; ENABLE + FORCE row-level security with a tenant policy on PostgreSQL.
Idempotent; downgrade drops only this table.

Revision ID: 161
Revises: 160
"""
from alembic import op

revision = "161"
down_revision = "160"
branch_labels = None
depends_on = None

TABLE = "marketing_creative_jobs"


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
    ts = "TIMESTAMPTZ" if postgres else "TIMESTAMP"
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id               VARCHAR PRIMARY KEY,
            tenant_id        VARCHAR NOT NULL REFERENCES tenants(id),
            provider         VARCHAR(20) NOT NULL,
            kind             VARCHAR(20) NOT NULL,
            content_id       VARCHAR,
            inputs           JSON NOT NULL,
            external_id      VARCHAR(200),
            external_url     TEXT,
            idempotency_key  VARCHAR(64) NOT NULL,
            status           VARCHAR(20) NOT NULL DEFAULT 'pending',
            error            TEXT,
            asset_id         VARCHAR,
            polls            INTEGER NOT NULL DEFAULT 0,
            created_by       VARCHAR,
            created_at       {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at       {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_tenant_id ON {TABLE} (tenant_id)")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_status ON {TABLE} (status)")
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
