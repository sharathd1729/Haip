"""Google surfaces: Business Profile performance, Search Console search analytics, PageSpeed Insights.

  * gbp_daily_metrics (new): one row per (tenant, location, day, metric), from the Business Profile Performance API.
  * gsc_daily_totals (new): one row per (tenant, Search Console property, day).
  * gsc_search_rows (new): date x query x page x country x device rows, unique on (tenant, row_key = sha256).
  * pagespeed_runs (new): one row per (tenant, url, strategy, week).
Every table: tenant_id + forced RLS (tenant isolation policy). Idempotent (production runs create_all first).

Revision ID: 192
Revises: 191
"""

from alembic import op

revision = "192"
down_revision = "191"
branch_labels = None
depends_on = None

_TS = """
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()"""

_TABLES = {
    "gbp_daily_metrics": f"""
    id          VARCHAR PRIMARY KEY,
    tenant_id   VARCHAR NOT NULL REFERENCES tenants(id),
    location    VARCHAR(120) NOT NULL,
    day         DATE NOT NULL,
    metric      VARCHAR(60) NOT NULL,
    value       INTEGER NOT NULL DEFAULT 0,{_TS},
    CONSTRAINT uq_gbp_daily_metrics UNIQUE (tenant_id, location, day, metric)
""",
    "gsc_daily_totals": f"""
    id          VARCHAR PRIMARY KEY,
    tenant_id   VARCHAR NOT NULL REFERENCES tenants(id),
    property    VARCHAR(300) NOT NULL,
    day         DATE NOT NULL,
    clicks      INTEGER NOT NULL DEFAULT 0,
    impressions INTEGER NOT NULL DEFAULT 0,
    ctr         DOUBLE PRECISION,
    position    DOUBLE PRECISION,{_TS},
    CONSTRAINT uq_gsc_daily_totals UNIQUE (tenant_id, property, day)
""",
    "gsc_search_rows": f"""
    id          VARCHAR PRIMARY KEY,
    tenant_id   VARCHAR NOT NULL REFERENCES tenants(id),
    property    VARCHAR(300) NOT NULL,
    day         DATE NOT NULL,
    query       VARCHAR(500) NOT NULL,
    page        VARCHAR(1000) NOT NULL,
    country     VARCHAR(3) NOT NULL,
    device      VARCHAR(10) NOT NULL,
    clicks      INTEGER NOT NULL DEFAULT 0,
    impressions INTEGER NOT NULL DEFAULT 0,
    ctr         DOUBLE PRECISION,
    position    DOUBLE PRECISION,
    row_key     VARCHAR(64) NOT NULL,{_TS},
    CONSTRAINT uq_gsc_search_rows_key UNIQUE (tenant_id, row_key)
""",
    "pagespeed_runs": f"""
    id              VARCHAR PRIMARY KEY,
    tenant_id       VARCHAR NOT NULL REFERENCES tenants(id),
    site_id         VARCHAR,
    url             VARCHAR(1000) NOT NULL,
    label           VARCHAR(120),
    strategy        VARCHAR(10) NOT NULL,
    week_of         DATE NOT NULL,
    measured_at     TIMESTAMPTZ,
    lab_performance INTEGER,
    lab_lcp_ms      INTEGER,
    lab_cls         DOUBLE PRECISION,
    lab_tbt_ms      INTEGER,
    field_lcp_ms    INTEGER,
    field_inp_ms    INTEGER,
    field_cls       DOUBLE PRECISION,
    field_category  VARCHAR(12),
    field_is_origin BOOLEAN NOT NULL DEFAULT FALSE,
    error           VARCHAR(200),{_TS},
    CONSTRAINT uq_pagespeed_runs UNIQUE (tenant_id, url, strategy, week_of)
""",
}


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
    for table, cols in _TABLES.items():
        op.execute(f"CREATE TABLE IF NOT EXISTS {table} ({cols})")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)")
        if postgres:
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
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_gsc_search_rows_tenant_property_day ON gsc_search_rows (tenant_id, property, day)"
    )


def downgrade():
    for table in reversed(list(_TABLES)):
        op.execute(f"DROP TABLE IF EXISTS {table}")
