"""Marketing agency foundations: run log (marketing_tasks) and per-post daily Instagram metrics.

New tables only; tenant_id NOT NULL; ENABLE + FORCE row-level security with a tenant policy on PostgreSQL.
Idempotent; downgrade drops only these tables.

Revision ID: 155
Revises: 154
"""
from alembic import op

revision = "155"
down_revision = "154"
branch_labels = None
depends_on = None

_TABLES = {
    "marketing_tasks": """
        id VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        run_id VARCHAR,
        role VARCHAR(30) NOT NULL,
        step VARCHAR(40) NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'queued',
        trigger VARCHAR(20) NOT NULL DEFAULT 'schedule',
        ref_type VARCHAR(40),
        ref_id VARCHAR,
        detail JSON,
        error TEXT,
        finished_at TIMESTAMPTZ,
        created_by VARCHAR,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
    "instagram_post_metrics_daily": """
        id VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        media_id VARCHAR(100) NOT NULL,
        day VARCHAR(10) NOT NULL,
        media_type VARCHAR(20),
        posted_at VARCHAR(50),
        like_count INTEGER,
        comments_count INTEGER,
        reach INTEGER,
        saved INTEGER,
        shares INTEGER,
        total_interactions INTEGER,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_ig_post_metrics_daily UNIQUE (tenant_id, media_id, day)
    """,
}
_INDEXES = [
    ("marketing_tasks", "ix_marketing_tasks_run_id", "(run_id)"),
    ("marketing_tasks", "ix_marketing_tasks_tenant_created", "(tenant_id, created_at)"),
]


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
    for table, cols in _TABLES.items():
        op.execute(f"CREATE TABLE IF NOT EXISTS {table} ({cols})")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)")
    for table, name, cols in _INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} {cols}")
    if postgres:
        for table in _TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_policies WHERE tablename = '{table}' AND policyname = '{table}_tenant_isolation'
                    ) THEN
                        CREATE POLICY {table}_tenant_isolation ON {table}
                        USING (tenant_id = current_setting('app.tenant_id', true)::text);
                    END IF;
                END
                $$
            """)


def downgrade():
    for table in ("instagram_post_metrics_daily", "marketing_tasks"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
