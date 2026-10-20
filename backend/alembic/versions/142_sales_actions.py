"""AI sales agent: ``sales_actions`` (a quote the agent prepared, bound to that exact quote, and what happened to it)

The sales agent itself is off for every tenant: ``brand_config.sales_agent.mode`` defaults to "off" and only the owner can
change it (PUT /ai/sales-agent, audited). This migration only adds the table, with tenant_id and row-level security.
Production builds tables with create_all at startup (no RLS), so every statement is guarded and the migration is idempotent.

Revision ID: 142
Revises: 141
Create Date: 2026-10-18
"""
from alembic import op

revision = "142"
down_revision = "141"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS sales_actions (
            id               VARCHAR PRIMARY KEY,
            tenant_id        VARCHAR NOT NULL,
            inquiry_id       VARCHAR NOT NULL REFERENCES inquiries(id),
            conversation_id  VARCHAR,
            message_id       VARCHAR,
            quote_id         VARCHAR NOT NULL,
            kind             VARCHAR(20) NOT NULL DEFAULT 'send_quote',
            mode             VARCHAR(12) NOT NULL,
            status           VARCHAR(12) NOT NULL DEFAULT 'pending',
            requirement_key  VARCHAR(64) NOT NULL,
            summary          JSON NOT NULL DEFAULT '{}',
            hold_reasons     JSON NOT NULL DEFAULT '[]',
            last_error       TEXT,
            decided_by       VARCHAR,
            decided_at       TIMESTAMPTZ,
            result           JSON,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_sales_actions_tenant_id ON sales_actions (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sales_actions_tenant_inquiry ON sales_actions (tenant_id, inquiry_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sales_actions_tenant_status ON sales_actions (tenant_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sales_actions_conversation_id ON sales_actions (conversation_id)")
    op.execute("ALTER TABLE sales_actions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sales_actions FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies WHERE tablename = 'sales_actions' AND policyname = 'sales_actions_tenant_isolation'
            ) THEN
                CREATE POLICY sales_actions_tenant_isolation ON sales_actions
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
            END IF;
        END
        $$
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS sales_actions")
