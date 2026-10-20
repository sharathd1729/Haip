"""Marketing agency phase C: schedule + publish attempts (Instagram content publishing).

New table only; tenant_id NOT NULL; ENABLE + FORCE row-level security with a tenant policy on PostgreSQL.
UNIQUE (content_id, version_id) makes publishing idempotent per approved version. marketing_content.status gains
the values 'scheduled' and 'published' (VARCHAR, no schema change). Idempotent; downgrade drops only this table.

Revision ID: 157
Revises: 156
"""
from alembic import op

revision = "157"
down_revision = "156"
branch_labels = None
depends_on = None

TABLE = "marketing_publish_attempts"


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id             VARCHAR PRIMARY KEY,
            tenant_id      VARCHAR NOT NULL REFERENCES tenants(id),
            content_id     VARCHAR NOT NULL REFERENCES marketing_content(id),
            version_id     VARCHAR NOT NULL,
            sha256         VARCHAR(64) NOT NULL,
            scheduled_for  TIMESTAMPTZ NOT NULL,
            status         VARCHAR(20) NOT NULL DEFAULT 'scheduled',
            container_ids  JSON,
            media_ids      JSON,
            permalink      TEXT,
            error          TEXT,
            tries          INTEGER NOT NULL DEFAULT 0,
            scheduled_by   VARCHAR,
            published_at   TIMESTAMPTZ,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_marketing_publish_attempts_version UNIQUE (content_id, version_id)
        )
    """)
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_tenant_id ON {TABLE} (tenant_id)")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_content_id ON {TABLE} (content_id)")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_due ON {TABLE} (status, scheduled_for)")
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
