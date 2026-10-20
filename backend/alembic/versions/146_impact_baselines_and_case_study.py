"""Impact view: owner-entered baselines and the case-study snapshot

* ``impact_baselines``: one row per (tenant, metric): the "before HAIP" figure the owner typed in, its period and source.
* ``impact_profiles``: one row per tenant: go-live date, case-study slug, status and the published snapshot (aggregates).
* ``impact_published_case_study(p_slug)``: SECURITY DEFINER lookup for the public, unauthenticated case-study page. It
  returns ONLY published snapshots (slug, snapshot, published_at), so the page never needs a tenant context and can
  never read a draft, a baseline or anything else of the tenant. ``p_slug`` NULL lists every published one.

Both tables carry tenant_id + row-level security. Production builds tables with create_all at startup, so every
statement is guarded (IF NOT EXISTS / pg_policies check / CREATE OR REPLACE).

Revision ID: 146
Revises: 144
Create Date: 2026-10-18
"""
from alembic import op

revision = "146"
down_revision = "144"
branch_labels = None
depends_on = None

_TABLES = ("impact_baselines", "impact_profiles")


def _rls(table: str) -> None:
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)")
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


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS impact_baselines (
            id            VARCHAR PRIMARY KEY,
            tenant_id     VARCHAR NOT NULL,
            metric        VARCHAR(60) NOT NULL,
            value         NUMERIC(14, 2) NOT NULL,
            period_label  VARCHAR(80) NOT NULL,
            source_note   TEXT,
            created_by    VARCHAR REFERENCES users(id),
            updated_by    VARCHAR REFERENCES users(id),
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_impact_baselines_tenant_metric UNIQUE (tenant_id, metric)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS impact_profiles (
            id                  VARCHAR PRIMARY KEY,
            tenant_id           VARCHAR NOT NULL,
            go_live_date        DATE,
            window_days         INTEGER NOT NULL DEFAULT 30,
            case_study_slug     VARCHAR(40),
            case_study_status   VARCHAR(12) NOT NULL DEFAULT 'draft',
            case_study_snapshot JSON,
            published_at        TIMESTAMPTZ,
            published_by        VARCHAR REFERENCES users(id),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_impact_profiles_tenant UNIQUE (tenant_id),
            CONSTRAINT uq_impact_profiles_slug UNIQUE (case_study_slug)
        )
    """)
    for t in _TABLES:
        _rls(t)
    op.execute("""
        CREATE OR REPLACE FUNCTION impact_published_case_study(p_slug text)
        RETURNS TABLE (slug text, snapshot json, published_at timestamptz)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
        $$ SELECT case_study_slug::text, case_study_snapshot, published_at FROM impact_profiles
           WHERE case_study_status = 'published' AND case_study_snapshot IS NOT NULL AND case_study_slug IS NOT NULL
             AND (p_slug IS NULL OR case_study_slug = p_slug)
           ORDER BY published_at DESC $$
    """)


def downgrade():
    op.execute("DROP FUNCTION IF EXISTS impact_published_case_study(text)")
    for t in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {t}")
