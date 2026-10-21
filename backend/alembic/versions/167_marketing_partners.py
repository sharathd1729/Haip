"""Marketing agency M7 (partnerships + reputation loop): creators, creator deals, OTA copy; review -> post consent.

Three new tables, tenant_id NOT NULL, ENABLE + FORCE row-level security with a tenant policy on PostgreSQL.
UNIQUE (tenant_id, platform, handle) on creators. Nullable columns on marketing_guest_reviews (its RLS policy is
unchanged): content_id, consent_note, consent_by, consent_at -- a review becomes a post only after a person records
that the guest agreed. Idempotent; downgrade drops only these.

Revision ID: 167
Revises: 166
"""
from alembic import op

revision = "167"
down_revision = "166"
branch_labels = None
depends_on = None

TABLES = ("marketing_creators", "marketing_creator_deals", "marketing_ota_copies")
REVIEW_COLUMNS = (("content_id", "VARCHAR"), ("consent_note", "VARCHAR(300)"), ("consent_by", "VARCHAR"),
                  ("consent_at", "TIMESTAMPTZ"))


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
        CREATE TABLE IF NOT EXISTS marketing_creators (
            id          VARCHAR PRIMARY KEY,
            tenant_id   VARCHAR NOT NULL REFERENCES tenants(id),
            platform    VARCHAR(20) NOT NULL DEFAULT 'instagram',
            handle      VARCHAR(40) NOT NULL,
            name        VARCHAR(120),
            followers   INTEGER,
            niche       VARCHAR(120),
            notes       TEXT,
            guest_id    VARCHAR,
            status      VARCHAR(20) NOT NULL DEFAULT 'active',
            created_by  VARCHAR,
            created_at  {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at  {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_marketing_creators_handle UNIQUE (tenant_id, platform, handle)
        )
    """)
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS marketing_creator_deals (
            id              VARCHAR PRIMARY KEY,
            tenant_id       VARCHAR NOT NULL REFERENCES tenants(id),
            creator_id      VARCHAR NOT NULL REFERENCES marketing_creators(id),
            status          VARCHAR(20) NOT NULL DEFAULT 'requested',
            property_id     VARCHAR,
            check_in        DATE,
            check_out       DATE,
            guests          INTEGER NOT NULL DEFAULT 2,
            comp_value_inr  INTEGER NOT NULL DEFAULT 0,
            deliverables    JSON NOT NULL,
            notes           TEXT,
            stay_id         VARCHAR,
            created_by      VARCHAR,
            approved_by     VARCHAR,
            approved_at     {ts},
            closed_at       {ts},
            created_at      {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS marketing_ota_copies (
            id              VARCHAR PRIMARY KEY,
            tenant_id       VARCHAR NOT NULL REFERENCES tenants(id),
            property_id     VARCHAR NOT NULL,
            platform        VARCHAR(20) NOT NULL,
            status          VARCHAR(20) NOT NULL DEFAULT 'pending',
            body            JSON,
            error           TEXT,
            model           VARCHAR(120),
            prompt_version  VARCHAR(60),
            created_by      VARCHAR,
            created_at      {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for t in TABLES:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{t}_tenant_id ON {t} (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_marketing_creator_deals_creator_id ON marketing_creator_deals (creator_id)")
    if postgres:
        for name, kind in REVIEW_COLUMNS:
            op.execute(f"ALTER TABLE marketing_guest_reviews ADD COLUMN IF NOT EXISTS {name} {kind}")
        for t in TABLES:
            _rls(t)
    else:
        existing = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(marketing_guest_reviews)")}
        for name, kind in REVIEW_COLUMNS:
            if name not in existing:
                op.execute(f"ALTER TABLE marketing_guest_reviews ADD COLUMN {name} {kind.replace('TIMESTAMPTZ', 'TIMESTAMP')}")


def downgrade():
    bind = op.get_bind()
    op.execute("DROP TABLE IF EXISTS marketing_ota_copies")
    op.execute("DROP TABLE IF EXISTS marketing_creator_deals")
    op.execute("DROP TABLE IF EXISTS marketing_creators")
    for name, _ in REVIEW_COLUMNS:
        if bind.dialect.name == "postgresql":
            op.execute(f"ALTER TABLE marketing_guest_reviews DROP COLUMN IF EXISTS {name}")
        else:
            op.drop_column("marketing_guest_reviews", name)
