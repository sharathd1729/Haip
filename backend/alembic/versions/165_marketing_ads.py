"""Marketing agency M5 (performance marketer): ad drafts, boost rules, Conversions API events.

Three new tables, tenant_id NOT NULL, ENABLE + FORCE row-level security with a tenant policy on PostgreSQL.
UNIQUE (tenant_id, rule_id, window_key): a rule boosts one weekend once. UNIQUE (tenant_id, stay_id, event_name): a
booking is sent to Meta once. Idempotent; downgrade drops only these.

Revision ID: 165
Revises: 164
"""
from alembic import op

revision = "165"
down_revision = "164"
branch_labels = None
depends_on = None

TABLES = ("marketing_boost_rules", "marketing_ad_drafts", "marketing_capi_events")


def _rls(table: str) -> None:
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
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    ts = "TIMESTAMPTZ" if postgres else "TIMESTAMP"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS marketing_boost_rules (
            id               VARCHAR PRIMARY KEY,
            tenant_id        VARCHAR NOT NULL REFERENCES tenants(id),
            name             VARCHAR(80) NOT NULL,
            body             JSON NOT NULL,
            body_sha         VARCHAR(64) NOT NULL,
            status           VARCHAR(20) NOT NULL DEFAULT 'draft',
            created_by       VARCHAR,
            approved_by      VARCHAR,
            approved_at      {ts},
            approved_sha     VARCHAR(64),
            last_checked_at  {ts},
            last_result      JSON,
            created_at       {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at       {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS marketing_ad_drafts (
            id                VARCHAR PRIMARY KEY,
            tenant_id         VARCHAR NOT NULL REFERENCES tenants(id),
            content_id        VARCHAR NOT NULL REFERENCES marketing_content(id),
            version_id        VARCHAR NOT NULL,
            content_sha       VARCHAR(64) NOT NULL,
            origin            VARCHAR(10) NOT NULL DEFAULT 'manual',
            rule_id           VARCHAR REFERENCES marketing_boost_rules(id),
            window_key        VARCHAR(40),
            destination       VARCHAR(20) NOT NULL,
            daily_budget_inr  INTEGER NOT NULL,
            days              INTEGER NOT NULL,
            spend_cap_inr     INTEGER NOT NULL,
            audience          JSON NOT NULL,
            status            VARCHAR(20) NOT NULL DEFAULT 'draft',
            created_by        VARCHAR,
            approved_by       VARCHAR,
            approved_at       {ts},
            approval_note     VARCHAR(300),
            meta              JSON,
            starts_at         {ts},
            ends_at           {ts},
            spent_inr         NUMERIC(14, 2),
            tries             INTEGER NOT NULL DEFAULT 0,
            error             TEXT,
            created_at        {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at        {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_marketing_ad_drafts_rule_window UNIQUE (tenant_id, rule_id, window_key)
        )
    """)
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS marketing_capi_events (
            id             VARCHAR PRIMARY KEY,
            tenant_id      VARCHAR NOT NULL REFERENCES tenants(id),
            stay_id        VARCHAR NOT NULL,
            event_name     VARCHAR(40) NOT NULL DEFAULT 'Purchase',
            event_id       VARCHAR(80) NOT NULL,
            value          NUMERIC(14, 2),
            currency       VARCHAR(3) NOT NULL DEFAULT 'INR',
            action_source  VARCHAR(30),
            status         VARCHAR(20) NOT NULL DEFAULT 'pending',
            reason         VARCHAR(300),
            tries          INTEGER NOT NULL DEFAULT 0,
            sent_at        {ts},
            fbtrace_id     VARCHAR(80),
            created_at     {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at     {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_marketing_capi_events_stay UNIQUE (tenant_id, stay_id, event_name)
        )
    """)
    for t in TABLES:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{t}_tenant_id ON {t} (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_marketing_ad_drafts_content_id ON marketing_ad_drafts (content_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_marketing_ad_drafts_rule_id ON marketing_ad_drafts (rule_id)")
    if postgres:
        for t in TABLES:
            _rls(t)


def downgrade():
    op.execute("DROP TABLE IF EXISTS marketing_capi_events")
    op.execute("DROP TABLE IF EXISTS marketing_ad_drafts")
    op.execute("DROP TABLE IF EXISTS marketing_boost_rules")
