"""Marketing agency phase B: competitors, competitor snapshots/posts, research briefs.

New tables only; tenant_id NOT NULL; ENABLE + FORCE row-level security with a tenant policy on PostgreSQL.
API-sourced competitor data (snapshots, posts with source='api') is deleted when the Facebook connection is removed
(Meta Platform Terms); manual entries stay. Idempotent; downgrade drops only these tables.

Revision ID: 132
Revises: 131
"""
from alembic import op

revision = "132"
down_revision = "131"
branch_labels = None
depends_on = None

_TABLES = {
    "marketing_competitors": """
        id VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        handle VARCHAR(31) NOT NULL,
        display_name VARCHAR(120),
        notes TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        created_by VARCHAR,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_marketing_competitors_handle UNIQUE (tenant_id, handle)
    """,
    "marketing_competitor_snapshots": """
        id VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        competitor_id VARCHAR NOT NULL REFERENCES marketing_competitors(id),
        source VARCHAR(10) NOT NULL DEFAULT 'api',
        followers_count INTEGER,
        media_count INTEGER,
        error TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
    "marketing_competitor_posts": """
        id VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        competitor_id VARCHAR NOT NULL REFERENCES marketing_competitors(id),
        source VARCHAR(10) NOT NULL,
        media_id VARCHAR(100),
        permalink VARCHAR(300),
        caption TEXT,
        media_type VARCHAR(20),
        like_count INTEGER,
        comments_count INTEGER,
        posted_at VARCHAR(50),
        note TEXT,
        created_by VARCHAR,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
    "marketing_research_briefs": """
        id VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        measured JSON NOT NULL,
        assessment JSON,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        error TEXT,
        prompt_version VARCHAR(60),
        model VARCHAR(120),
        created_by VARCHAR,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    """,
}
_INDEXES = [
    ("marketing_competitor_snapshots", "ix_marketing_competitor_snapshots_competitor_id", "(competitor_id)"),
    ("marketing_competitor_posts", "ix_marketing_competitor_posts_competitor_id", "(competitor_id)"),
    ("marketing_competitor_posts", "ix_marketing_competitor_posts_comp_media", "(competitor_id, media_id)"),
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
    for table in ("marketing_research_briefs", "marketing_competitor_posts", "marketing_competitor_snapshots",
                  "marketing_competitors"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
