"""WhatsApp growth tools (WhatsApp step 3): wa_entry_links.

A named click-to-chat link (wa.me with a prefilled first message carrying "(ref w-xxxxxxxx)"), its QR code and
website chat button. Counts taps (GET /api/v1/w/{code}) and chats started (an inbound message with the ref).
tenant_id + forced RLS. Idempotent (IF NOT EXISTS, guarded policy) because production runs create_all at startup.

Revision ID: 214
Revises: 213
"""
from alembic import op

revision = "214"
down_revision = "213"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS wa_entry_links (
            id              VARCHAR PRIMARY KEY,
            tenant_id       VARCHAR NOT NULL REFERENCES tenants(id),
            code            VARCHAR(16) NOT NULL,
            name            VARCHAR(80) NOT NULL,
            prefill_text    VARCHAR(500) NOT NULL DEFAULT '',
            phone           VARCHAR(20) NOT NULL,
            clicks          INTEGER NOT NULL DEFAULT 0,
            chats           INTEGER NOT NULL DEFAULT 0,
            last_clicked_at TIMESTAMPTZ,
            active          BOOLEAN NOT NULL DEFAULT TRUE,
            created_by      VARCHAR,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_wa_entry_links_code UNIQUE (code)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_wa_entry_links_tenant_id ON wa_entry_links (tenant_id)")
    op.execute("ALTER TABLE wa_entry_links ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE wa_entry_links FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'wa_entry_links'
                           AND policyname = 'wa_entry_links_tenant_isolation') THEN
                CREATE POLICY wa_entry_links_tenant_isolation ON wa_entry_links
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
            END IF;
        END
        $$
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS wa_entry_links")
