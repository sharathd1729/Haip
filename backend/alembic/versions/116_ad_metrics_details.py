"""Meta ads: more metrics per ad per day, and campaign / ad set / ad details

Adds link clicks, engagement, video views, first replies, cost per click, unique clicks and Meta's full
action list to ad_metrics, and a new ad_entities table (campaign, ad set and ad details: status, objective,
budget, dates, creative, audience) with tenant_id and row-level security.

create_all at API startup does not add columns to an existing table or add RLS, so every statement here is
idempotent and safe whichever of the two gets there first.

Revision ID: 116
Revises: 115
Create Date: 2026-10-12
"""
from alembic import op

revision = "116"
down_revision = "115"
branch_labels = None
depends_on = None


def upgrade():
    for col, ddl in (
        ("link_clicks", "INTEGER NOT NULL DEFAULT 0"),
        ("unique_clicks", "INTEGER NOT NULL DEFAULT 0"),
        ("post_engagement", "INTEGER NOT NULL DEFAULT 0"),
        ("video_views", "INTEGER NOT NULL DEFAULT 0"),
        ("first_replies", "INTEGER NOT NULL DEFAULT 0"),
        ("cpc", "NUMERIC(12, 4) NOT NULL DEFAULT 0"),
        ("actions", "JSON"),
    ):
        op.execute(f"ALTER TABLE ad_metrics ADD COLUMN IF NOT EXISTS {col} {ddl}")

    op.execute("""
        CREATE TABLE IF NOT EXISTS ad_entities (
            id                VARCHAR PRIMARY KEY,
            tenant_id         VARCHAR NOT NULL,
            ad_account_id     VARCHAR(40) NOT NULL,
            level             VARCHAR(10) NOT NULL,
            entity_id         VARCHAR(60) NOT NULL,
            campaign_id       VARCHAR(60) NOT NULL DEFAULT '',
            adset_id          VARCHAR(60) NOT NULL DEFAULT '',
            name              VARCHAR(300) NOT NULL DEFAULT '',
            status            VARCHAR(30),
            effective_status  VARCHAR(40),
            objective         VARCHAR(60),
            optimization_goal VARCHAR(60),
            daily_budget      NUMERIC(14, 2),
            lifetime_budget   NUMERIC(14, 2),
            starts_at         TIMESTAMPTZ,
            ends_at           TIMESTAMPTZ,
            creative          JSON,
            targeting         JSON,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_ad_entities_tenant_level_entity UNIQUE (tenant_id, level, entity_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ad_entities_tenant_id ON ad_entities (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ad_entities_tenant_level ON ad_entities (tenant_id, level)")

    op.execute("ALTER TABLE ad_entities ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ad_entities FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE tablename = 'ad_entities' AND policyname = 'ad_entities_tenant_isolation'
            ) THEN
                CREATE POLICY ad_entities_tenant_isolation ON ad_entities
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
            END IF;
        END
        $$
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS ad_entities")
    for col in ("link_clicks", "unique_clicks", "post_engagement", "video_views", "first_replies", "cpc", "actions"):
        op.execute(f"ALTER TABLE ad_metrics DROP COLUMN IF EXISTS {col}")
