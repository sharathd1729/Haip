"""Ask a manager: ``agent_consults`` (the AI asks a person before it answers a guest)

One table, tenant_id NOT NULL, ENABLE + FORCE row-level security with a tenant policy, and a partial unique index so a
conversation has at most one OPEN consult. Settings live in brand_config (agent_consult / agent_policy / sales_playbook),
so no other schema change. Production builds tables with create_all at startup (no RLS), so every statement is guarded and
the migration is idempotent. Downgrade drops only this table.

Revision ID: 168
Revises: 167
Create Date: 2026-10-22
"""
from alembic import op

revision = "168"
down_revision = "167"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_consults (
            id                    VARCHAR PRIMARY KEY,
            tenant_id             VARCHAR NOT NULL,
            conversation_id       VARCHAR NOT NULL REFERENCES conversations(id),
            guest_id              VARCHAR,
            inquiry_id            VARCHAR,
            message_id            VARCHAR,
            draft_message_id      VARCHAR,
            holding_message_id    VARCHAR,
            channel               VARCHAR(20),
            reason_codes          JSON NOT NULL DEFAULT '[]',
            question              TEXT NOT NULL,
            proposed_answer       TEXT,
            options               JSON,
            evidence              JSON NOT NULL DEFAULT '{}',
            status                VARCHAR(12) NOT NULL DEFAULT 'open',
            level                 VARCHAR(10) NOT NULL DEFAULT 'agent',
            assigned_to           VARCHAR,
            sla_due_at            TIMESTAMPTZ NOT NULL,
            escalated_at          TIMESTAMPTZ,
            answered_by           VARCHAR,
            answer_mode           VARCHAR(20),
            answer_text           TEXT,
            answered_at           TIMESTAMPTZ,
            delivery              VARCHAR(20),
            answer_message_id     VARCHAR,
            task_id               VARCHAR,
            saved_to_kb_entry_id  VARCHAR,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_consults_tenant_id ON agent_consults (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_consults_tenant_status ON agent_consults (tenant_id, status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_consults_conversation_id ON agent_consults (conversation_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_consults_guest_id ON agent_consults (guest_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_agent_consults_inquiry_id ON agent_consults (inquiry_id)")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_consults_open_conversation
        ON agent_consults (tenant_id, conversation_id) WHERE status = 'open'
    """)
    op.execute("ALTER TABLE agent_consults ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agent_consults FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies WHERE tablename = 'agent_consults' AND policyname = 'agent_consults_tenant_isolation'
            ) THEN
                CREATE POLICY agent_consults_tenant_isolation ON agent_consults
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
            END IF;
        END
        $$
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS agent_consults")
