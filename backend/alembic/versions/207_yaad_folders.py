"""Yaad folders (personal workspaces, services/personal_folders.py): yaad_folders + yaad_folder_calls.

A folder is made only by the person (never automatically): a name, keywords and a sorting prompt in their own words.
A summarised call is filed into every folder its keywords or prompt match (source "auto"); the person can add (source
"manual") or remove a call: a removed call keeps its row with excluded = true, so sorting never puts it back.
tenant_id + forced RLS on both. Idempotent (IF NOT EXISTS, guarded policy) because production runs create_all at startup.

Revision ID: 207
Revises: 206
"""

from alembic import op

revision = "207"
down_revision = "206"
branch_labels = None
depends_on = None

_RLS = """
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = '{t}' AND policyname = '{t}_tenant_isolation') THEN
            CREATE POLICY {t}_tenant_isolation ON {t} USING (tenant_id = current_setting('app.tenant_id', true)::text);
        END IF;
    END
    $$
"""


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS yaad_folders (
            id          VARCHAR PRIMARY KEY,
            tenant_id   VARCHAR NOT NULL REFERENCES tenants(id),
            name        VARCHAR(80) NOT NULL,
            color       VARCHAR(20) NOT NULL DEFAULT 'mango',
            keywords    JSON NOT NULL DEFAULT '[]',
            prompt      TEXT NOT NULL DEFAULT '',
            created_by  VARCHAR REFERENCES users(id),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_yaad_folders_tenant_id ON yaad_folders (tenant_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS yaad_folder_calls (
            id          VARCHAR PRIMARY KEY,
            tenant_id   VARCHAR NOT NULL REFERENCES tenants(id),
            folder_id   VARCHAR NOT NULL REFERENCES yaad_folders(id) ON DELETE CASCADE,
            call_id     VARCHAR NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
            source      VARCHAR(10) NOT NULL DEFAULT 'auto',
            excluded    BOOLEAN NOT NULL DEFAULT false,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_yaad_folder_calls_folder_call UNIQUE (folder_id, call_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_yaad_folder_calls_tenant_call ON yaad_folder_calls (tenant_id, call_id)")
    for t in ("yaad_folders", "yaad_folder_calls"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(_RLS.format(t=t))


def downgrade():
    op.execute("DROP TABLE IF EXISTS yaad_folder_calls")
    op.execute("DROP TABLE IF EXISTS yaad_folders")
