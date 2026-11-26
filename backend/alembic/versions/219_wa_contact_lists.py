"""WhatsApp contact lists (SMS9 parity, Track B): named lists such as "Wedding enquiries 2026", separate from tags.

- wa_contact_lists: the list names (tenant_id + forced RLS).
- wa_subscribers.list_ids: JSON list of wa_contact_lists ids the contact is on (filtered like conversations.labels).

Idempotent (IF NOT EXISTS, guarded policy) because production runs create_all at startup.

Revision ID: 219
Revises: 218
"""
from alembic import op

revision = "219"
down_revision = "218"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS wa_contact_lists (
            id          VARCHAR PRIMARY KEY,
            tenant_id   VARCHAR NOT NULL REFERENCES tenants(id),
            name        VARCHAR(80) NOT NULL,
            created_by  VARCHAR,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_wa_contact_lists_tenant_name UNIQUE (tenant_id, name)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_wa_contact_lists_tenant_id ON wa_contact_lists (tenant_id)")
    op.execute("ALTER TABLE wa_contact_lists ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE wa_contact_lists FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'wa_contact_lists'
                           AND policyname = 'wa_contact_lists_tenant_isolation') THEN
                CREATE POLICY wa_contact_lists_tenant_isolation ON wa_contact_lists
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
            END IF;
        END
        $$
    """)
    op.execute("ALTER TABLE wa_subscribers ADD COLUMN IF NOT EXISTS list_ids JSON")


def downgrade():
    op.execute("ALTER TABLE wa_subscribers DROP COLUMN IF EXISTS list_ids")
    op.execute("DROP TABLE IF EXISTS wa_contact_lists")
