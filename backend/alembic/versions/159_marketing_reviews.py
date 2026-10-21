"""Marketing agency M1: brand reviews of draft text.

New table only; tenant_id NOT NULL; ENABLE + FORCE row-level security with a tenant policy on PostgreSQL.
UNIQUE (content_id, text_sha): one review per distinct text of a content item. Idempotent; downgrade drops only
this table.

Revision ID: 159
Revises: 158
"""
from alembic import op

revision = "159"
down_revision = "158"
branch_labels = None
depends_on = None

TABLE = "marketing_reviews"


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id              VARCHAR PRIMARY KEY,
            tenant_id       VARCHAR NOT NULL REFERENCES tenants(id),
            content_id      VARCHAR NOT NULL REFERENCES marketing_content(id),
            version_id      VARCHAR NOT NULL,
            text_sha        VARCHAR(64) NOT NULL,
            findings        JSON NOT NULL,
            blocking        BOOLEAN NOT NULL DEFAULT FALSE,
            advice          JSON,
            summary         TEXT,
            ai_status       VARCHAR(20) NOT NULL DEFAULT 'skipped',
            ai_error        TEXT,
            model           VARCHAR(120),
            prompt_version  VARCHAR(60),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_marketing_reviews_text UNIQUE (content_id, text_sha)
        )
    """)
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_tenant_id ON {TABLE} (tenant_id)")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_content_id ON {TABLE} (content_id)")
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
