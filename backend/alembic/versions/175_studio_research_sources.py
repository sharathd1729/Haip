"""Marketing Studio phase 2 (plan 24 Oct 2026): research signals, the swipe file, collector columns on competitor posts.

  * marketing_signals (new tenant table, ENABLE + FORCE RLS + tenant policy): one observation per source, key and day
  * marketing_swipe_items (new tenant table, same RLS): hooks / shots read from Reels
  * marketing_competitor_posts.views / duration_s / audio_name / hashtags / media_url / media_key / media_expires_at
Idempotent (IF NOT EXISTS, guarded policies), so it repairs tables production built with create_all. Downgrade drops
only what this adds.

Revision ID: 175
Revises: 174
Create Date: 2026-10-24
"""
from alembic import op

revision = "175"
down_revision = "174"
branch_labels = None
depends_on = None

COLUMNS = (
    ("marketing_competitor_posts", "views", "INTEGER"),
    ("marketing_competitor_posts", "duration_s", "DOUBLE PRECISION"),
    ("marketing_competitor_posts", "audio_name", "VARCHAR(200)"),
    ("marketing_competitor_posts", "hashtags", "JSON"),
    ("marketing_competitor_posts", "media_url", "TEXT"),
    ("marketing_competitor_posts", "media_key", "VARCHAR(300)"),
    ("marketing_competitor_posts", "media_expires_at", "TIMESTAMPTZ"),
)
TABLES = ("marketing_signals", "marketing_swipe_items")


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = '{table}' AND policyname = '{table}_tenant_isolation') THEN
                CREATE POLICY {table}_tenant_isolation ON {table} USING (tenant_id = current_setting('app.tenant_id', true)::text);
            END IF;
        END
        $$
    """)


def upgrade():
    bind = op.get_bind()
    pg = bind.dialect.name == "postgresql"
    ts = "TIMESTAMPTZ" if pg else "TIMESTAMP"
    if pg:
        op.execute("SET LOCAL lock_timeout = '10s'")
    for table, name, kind in COLUMNS:
        kind = kind if pg else kind.replace("TIMESTAMPTZ", "TIMESTAMP")
        if pg:
            op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {kind}")
        elif name not in {row[1] for row in bind.exec_driver_sql(f"PRAGMA table_info({table})")}:
            op.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS marketing_signals (
            id VARCHAR PRIMARY KEY, tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
            source VARCHAR(20) NOT NULL, evidence VARCHAR(10) NOT NULL, key VARCHAR(200) NOT NULL, title TEXT, url TEXT,
            value DOUBLE PRECISION, data JSON, query VARCHAR(200), observed_on DATE NOT NULL,
            created_at {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_marketing_signals_day UNIQUE (tenant_id, source, key, observed_on)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_marketing_signals_tenant_id ON marketing_signals (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_marketing_signals_tenant_source_day ON marketing_signals (tenant_id, source, observed_on)")
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS marketing_swipe_items (
            id VARCHAR PRIMARY KEY, tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
            evidence VARCHAR(10) NOT NULL DEFAULT 'platform', competitor_post_id VARCHAR, source_url TEXT,
            status VARCHAR(12) NOT NULL DEFAULT 'pending', reading JSON, cut_times JSON, pacing VARCHAR(10), error TEXT,
            model VARCHAR(120), prompt_version VARCHAR(60),
            created_at {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_marketing_swipe_items_tenant_id ON marketing_swipe_items (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_marketing_swipe_items_competitor_post_id ON marketing_swipe_items (competitor_post_id)")
    if pg:
        for t in TABLES:
            _rls(t)


def downgrade():
    bind = op.get_bind()
    for t in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {t}")
    for table, name, _ in COLUMNS:
        if bind.dialect.name == "postgresql":
            op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {name}")
        else:
            op.drop_column(table, name)
