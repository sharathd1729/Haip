"""Meta ad performance: daily ad-level insights

New table ad_metrics (one row per ad per day) with tenant_id and row-level security. Production builds
tables with create_all at API startup, which does not add RLS, so this migration creates the table when it
is missing and always enables RLS and the policy. Every statement is idempotent.

Revision ID: 115
Revises: 114
Create Date: 2026-10-11
"""
from alembic import op

revision = "115"
down_revision = "114"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS ad_metrics (
            id                    VARCHAR PRIMARY KEY,
            tenant_id             VARCHAR NOT NULL,
            ad_account_id         VARCHAR(40) NOT NULL,
            date                  DATE NOT NULL,
            campaign_id           VARCHAR(60) NOT NULL DEFAULT '',
            campaign_name         VARCHAR(300) NOT NULL DEFAULT '',
            adset_id              VARCHAR(60) NOT NULL DEFAULT '',
            adset_name            VARCHAR(300) NOT NULL DEFAULT '',
            ad_id                 VARCHAR(60) NOT NULL,
            ad_name               VARCHAR(300) NOT NULL DEFAULT '',
            spend                 NUMERIC(14, 2) NOT NULL DEFAULT 0,
            impressions           BIGINT NOT NULL DEFAULT 0,
            reach                 BIGINT NOT NULL DEFAULT 0,
            clicks                INTEGER NOT NULL DEFAULT 0,
            frequency             NUMERIC(8, 3) NOT NULL DEFAULT 0,
            ctr                   NUMERIC(8, 4) NOT NULL DEFAULT 0,
            cpm                   NUMERIC(12, 4) NOT NULL DEFAULT 0,
            conversations_started INTEGER NOT NULL DEFAULT 0,
            leads                 INTEGER NOT NULL DEFAULT 0,
            currency              VARCHAR(3) NOT NULL DEFAULT 'INR',
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ad_metrics_tenant_date_ad UNIQUE (tenant_id, date, ad_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ad_metrics_tenant_id ON ad_metrics (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ad_metrics_tenant_date ON ad_metrics (tenant_id, date)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ad_metrics_tenant_campaign ON ad_metrics (tenant_id, campaign_id)")

    op.execute("ALTER TABLE ad_metrics ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ad_metrics FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'ad_metrics' AND policyname = 'ad_metrics_tenant_isolation'
            ) THEN
                CREATE POLICY ad_metrics_tenant_isolation ON ad_metrics
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
            END IF;
        END
        $$
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS ad_metrics")
