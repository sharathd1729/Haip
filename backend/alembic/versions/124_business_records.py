"""Versioned structured business records (packages, destinations, itineraries, commercial policies).

New table only: nothing existing is altered. One row per version of a record; a published version is immutable. Tenant-scoped like
every tenant table: tenant_id NOT NULL, row-level security enabled and forced on PostgreSQL with a tenant policy.

Idempotent (IF NOT EXISTS, guarded policy) so it can be re-run; downgrade drops only this table.

Revision ID: 124
Revises: 123
"""
from alembic import op

revision = "124"
down_revision = "123"
branch_labels = None
depends_on = None

TABLE = "business_records"


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id               VARCHAR PRIMARY KEY,
            tenant_id        VARCHAR NOT NULL REFERENCES tenants(id),
            kind             VARCHAR(30) NOT NULL,
            key              VARCHAR(60) NOT NULL,
            version          INTEGER NOT NULL,
            status           VARCHAR(20) NOT NULL DEFAULT 'draft',
            data             JSON NOT NULL,
            effective_from   DATE,
            effective_to     DATE,
            change_note      TEXT,
            created_by       VARCHAR,
            published_by     VARCHAR,
            published_at     TIMESTAMPTZ,
            rejected_by      VARCHAR,
            rejected_reason  TEXT,
            supersedes_id    VARCHAR,
            rollback_of_id   VARCHAR,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_{TABLE}_version UNIQUE (tenant_id, kind, key, version)
        )
    """)
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_tenant_id ON {TABLE} (tenant_id)")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_lookup ON {TABLE} (tenant_id, kind, key, status)")
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
