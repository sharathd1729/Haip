"""Ask Yaad sessions (personal workspaces, services/personal_ask.py): yaad_asks.

One row per chat: title (its first question), optional folder (answers only from that folder's calls) and the turns as
JSON (question, answer with [n] markers, sources with the call and the moment in the recording, follow-up questions).
tenant_id + forced RLS. Idempotent (IF NOT EXISTS, guarded policy) because production runs create_all at startup.

Revision ID: 209
Revises: 208
"""

from alembic import op

revision = "209"
down_revision = "208"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS yaad_asks (
            id          VARCHAR PRIMARY KEY,
            tenant_id   VARCHAR NOT NULL REFERENCES tenants(id),
            folder_id   VARCHAR REFERENCES yaad_folders(id) ON DELETE SET NULL,
            title       VARCHAR(160) NOT NULL,
            turns       JSON NOT NULL DEFAULT '[]',
            created_by  VARCHAR REFERENCES users(id),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_yaad_asks_tenant_updated ON yaad_asks (tenant_id, updated_at)")
    op.execute("ALTER TABLE yaad_asks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE yaad_asks FORCE ROW LEVEL SECURITY")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'yaad_asks'
                           AND policyname = 'yaad_asks_tenant_isolation') THEN
                CREATE POLICY yaad_asks_tenant_isolation ON yaad_asks
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
            END IF;
        END
        $$
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS yaad_asks")
