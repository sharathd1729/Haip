"""Marketing Studio phase 0 + 1 (plan 24 Oct 2026): AI images tied to their draft, ad watch-curve fields, Reel metrics,
creative tags.

  * marketing_image_jobs.content_id        -- the draft an AI image was requested for (filled into it once approved)
  * ad_metrics.video_thruplays / video_p25..p100 / video_avg_watch_s / link_ctr   -- Meta's watch curve + link CTR
  * instagram_post_metrics_daily.media_product_type / views / avg_watch_ms / skip_rate   -- every account post's views
    and, for Reels, average watch time and skip rate
  * marketing_creative_tags (new tenant table, ENABLE + FORCE RLS + tenant policy): one AI/owner tag record per post,
    Reel or ad
Nullable (or NOT NULL DEFAULT 0) columns on existing tenant tables, whose RLS policies are unchanged. ADD COLUMN IF NOT
EXISTS / CREATE TABLE IF NOT EXISTS / guarded policy, so it is idempotent and repairs tables production built with
create_all. Downgrade drops only what this adds.

Revision ID: 174
Revises: 173
Create Date: 2026-10-24
"""
from alembic import op

revision = "174"
down_revision = "173"
branch_labels = None
depends_on = None

COLUMNS = (
    ("marketing_image_jobs", "content_id", "VARCHAR"),
    ("ad_metrics", "video_thruplays", "INTEGER NOT NULL DEFAULT 0"),
    ("ad_metrics", "video_p25", "INTEGER NOT NULL DEFAULT 0"),
    ("ad_metrics", "video_p50", "INTEGER NOT NULL DEFAULT 0"),
    ("ad_metrics", "video_p75", "INTEGER NOT NULL DEFAULT 0"),
    ("ad_metrics", "video_p95", "INTEGER NOT NULL DEFAULT 0"),
    ("ad_metrics", "video_p100", "INTEGER NOT NULL DEFAULT 0"),
    ("ad_metrics", "video_avg_watch_s", "NUMERIC(10, 2) NOT NULL DEFAULT 0"),
    ("ad_metrics", "link_ctr", "NUMERIC(8, 4) NOT NULL DEFAULT 0"),
    ("instagram_post_metrics_daily", "media_product_type", "VARCHAR(20)"),
    ("instagram_post_metrics_daily", "views", "INTEGER"),
    ("instagram_post_metrics_daily", "avg_watch_ms", "INTEGER"),
    ("instagram_post_metrics_daily", "skip_rate", "DOUBLE PRECISION"),
)
TABLE = "marketing_creative_tags"


def _add_columns() -> None:
    bind = op.get_bind()
    for table, name, kind in COLUMNS:
        if bind.dialect.name == "postgresql":
            op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {name} {kind}")
        elif name not in {row[1] for row in bind.exec_driver_sql(f"PRAGMA table_info({table})")}:
            op.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")


def upgrade():
    pg = op.get_bind().dialect.name == "postgresql"
    if pg:
        op.execute("SET LOCAL lock_timeout = '10s'")
    _add_columns()
    ts = "TIMESTAMPTZ" if pg else "TIMESTAMP"
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id              VARCHAR PRIMARY KEY,
            tenant_id       VARCHAR NOT NULL REFERENCES tenants(id),
            subject_type    VARCHAR(10) NOT NULL,
            subject_id      VARCHAR(100) NOT NULL,
            content_id      VARCHAR,
            tags            JSON,
            status          VARCHAR(12) NOT NULL DEFAULT 'pending',
            source          VARCHAR(10) NOT NULL DEFAULT 'ai',
            error           TEXT,
            model           VARCHAR(120),
            prompt_version  VARCHAR(60),
            corrected_by    VARCHAR,
            corrected_at    {ts},
            created_at      {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_marketing_creative_tags_subject UNIQUE (tenant_id, subject_type, subject_id)
        )
    """)
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_tenant_id ON {TABLE} (tenant_id)")
    if pg:
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
    bind = op.get_bind()
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
    for table, name, _ in COLUMNS:
        if bind.dialect.name == "postgresql":
            op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {name}")
        else:
            op.drop_column(table, name)
