"""Marketing agency M3: email newsletters + their recipients.

Two new tables, tenant_id NOT NULL, ENABLE + FORCE row-level security with a tenant policy on PostgreSQL.
UNIQUE (newsletter_id, guest_id): nobody is emailed twice by one newsletter. Idempotent; downgrade drops only these.

Revision ID: 163
Revises: 162
"""
from alembic import op

revision = "163"
down_revision = "162"
branch_labels = None
depends_on = None

TABLES = ("marketing_newsletters", "marketing_newsletter_recipients")


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
        CREATE TABLE IF NOT EXISTS marketing_newsletters (
            id           VARCHAR PRIMARY KEY,
            tenant_id    VARCHAR NOT NULL REFERENCES tenants(id),
            subject      VARCHAR(200) NOT NULL,
            intro        TEXT,
            content_ids  JSON NOT NULL,
            status       VARCHAR(20) NOT NULL DEFAULT 'draft',
            created_by   VARCHAR,
            sent_by      VARCHAR,
            sent_at      {ts},
            recipients   INTEGER NOT NULL DEFAULT 0,
            delivered    INTEGER NOT NULL DEFAULT 0,
            failed       INTEGER NOT NULL DEFAULT 0,
            created_at   {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at   {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS marketing_newsletter_recipients (
            id             VARCHAR PRIMARY KEY,
            tenant_id      VARCHAR NOT NULL REFERENCES tenants(id),
            newsletter_id  VARCHAR NOT NULL REFERENCES marketing_newsletters(id),
            guest_id       VARCHAR NOT NULL,
            email          VARCHAR(255) NOT NULL,
            status         VARCHAR(20) NOT NULL DEFAULT 'queued',
            error          TEXT,
            sent_at        {ts},
            created_at     {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at     {ts} NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_marketing_newsletter_recipient UNIQUE (newsletter_id, guest_id)
        )
    """)
    for t in TABLES:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{t}_tenant_id ON {t} (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_marketing_newsletter_recipients_newsletter_id "
               "ON marketing_newsletter_recipients (newsletter_id)")
    if postgres:
        for t in TABLES:
            _rls(t)


def downgrade():
    op.execute("DROP TABLE IF EXISTS marketing_newsletter_recipients")
    op.execute("DROP TABLE IF EXISTS marketing_newsletters")
