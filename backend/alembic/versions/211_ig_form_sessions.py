"""Instagram DM forms: ig_form_sessions (one person answering one automation's questions).

While a session is active and not expired, the person's messages are answers to the current question: the AI concierge
and keyword rules stay quiet (services/ig_dm_form.py). tenant_id + forced RLS. Idempotent (IF NOT EXISTS, guarded
policy) because production runs create_all at startup.

Revision ID: 211
Revises: 210
"""

from alembic import op

revision = "211"
down_revision = "210"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS ig_form_sessions (
            id               VARCHAR PRIMARY KEY,
            tenant_id        VARCHAR NOT NULL REFERENCES tenants(id),
            rule_id          VARCHAR(36) NOT NULL,
            guest_id         VARCHAR NOT NULL,
            conversation_id  VARCHAR,
            recipient_id     VARCHAR(64) NOT NULL,
            step             INTEGER NOT NULL DEFAULT 0,
            answers          JSON NOT NULL DEFAULT '{}',
            status           VARCHAR(20) NOT NULL DEFAULT 'active',
            expires_at       TIMESTAMPTZ NOT NULL,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_ig_form_sessions_tenant_id ON ig_form_sessions (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ig_form_sessions_guest ON ig_form_sessions (tenant_id, guest_id, status)")
    op.execute("ALTER TABLE ig_form_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ig_form_sessions FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'ig_form_sessions'
                           AND policyname = 'ig_form_sessions_tenant_isolation') THEN
                CREATE POLICY ig_form_sessions_tenant_isolation ON ig_form_sessions
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
            END IF;
        END
        $$
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS ig_form_sessions")
