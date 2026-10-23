"""Marketing Studio phase 3 (plan 24 Oct 2026): the strategist's documents (shoot & collab briefs, monthly decks).

marketing_strategy_docs: new tenant table, ENABLE + FORCE RLS + tenant policy. The season calendar lives in
brand_config.marketing_studio.season_calendar (no schema). Idempotent; downgrade drops only this table.

Revision ID: 176
Revises: 175
Create Date: 2026-10-24
"""
from alembic import op

revision = "176"
down_revision = "175"
branch_labels = None
depends_on = None

TABLE = "marketing_strategy_docs"


def upgrade():
    pg = op.get_bind().dialect.name == "postgresql"
    ts = "TIMESTAMPTZ" if pg else "TIMESTAMP"
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id VARCHAR PRIMARY KEY, tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
            kind VARCHAR(10) NOT NULL, title VARCHAR(200) NOT NULL, period VARCHAR(10),
            status VARCHAR(12) NOT NULL DEFAULT 'pending', input JSON, facts JSON, body JSON, error TEXT,
            source VARCHAR(16), model VARCHAR(120), prompt_version VARCHAR(60), created_by VARCHAR,
            created_at {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_tenant_id ON {TABLE} (tenant_id)")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_tenant_kind ON {TABLE} (tenant_id, kind, created_at)")
    if pg:
        op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = '{TABLE}' AND policyname = '{TABLE}_tenant_isolation') THEN
                    CREATE POLICY {TABLE}_tenant_isolation ON {TABLE} USING (tenant_id = current_setting('app.tenant_id', true)::text);
                END IF;
            END
            $$
        """)


def downgrade():
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
