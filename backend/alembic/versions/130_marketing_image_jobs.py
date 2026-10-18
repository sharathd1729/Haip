"""Marketing Studio: AI image jobs (opt-in NVIDIA image generation).

New table only. tenant_id NOT NULL; on PostgreSQL ENABLE + FORCE row-level security with a tenant policy.
media_assets already has `status` (VARCHAR(20)), which gains the value 'pending_review' for AI images awaiting approval
(no schema change). Idempotent; downgrade drops only this table.

Revision ID: 130
Revises: 129
"""
from alembic import op

revision = "130"
down_revision = "129"
branch_labels = None
depends_on = None

TABLE = "marketing_image_jobs"


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id          VARCHAR PRIMARY KEY,
            tenant_id   VARCHAR NOT NULL REFERENCES tenants(id),
            prompt      TEXT NOT NULL,
            model       VARCHAR(60) NOT NULL,
            shape       VARCHAR(20) NOT NULL,
            seed        INTEGER,
            status      VARCHAR(20) NOT NULL DEFAULT 'pending',
            error       TEXT,
            asset_id    VARCHAR,
            created_by  VARCHAR,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_tenant_id ON {TABLE} (tenant_id)")
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
