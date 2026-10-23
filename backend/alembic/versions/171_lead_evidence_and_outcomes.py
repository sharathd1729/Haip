"""Lead evidence, the guest's location and the won/lost reason (sales meetings 22-23 Oct 2026).

New tenant-scoped table (tenant_id NOT NULL, ENABLE + FORCE row-level security with a tenant policy):
  * lead_evidence_imports      a WhatsApp chat export or a call recording a person uploaded onto a lead
                               (models/lead_evidence.py, services/lead_evidence_service.py)
New columns on an existing tenant-scoped table (its RLS policy is unchanged):
  * inquiries.guest_location VARCHAR(100)        the guest's starting city (lead validity rule, lead_validity.py)
  * inquiries.outcome_reason VARCHAR(30)         why the lead was won / lost (lead_outcome.CATALOGUE)
  * inquiries.outcome_reason_note VARCHAR(300)
  * inquiries.outcome_reason_source VARCHAR(20)  person | ai_confirmed | rule
  * inquiries.outcome_decided_by VARCHAR (users.id, SET NULL) / outcome_decided_at TIMESTAMPTZ
  * inquiries.outcome_proposal JSON              the AI's proposed reason + verbatim quotes (never a decision by itself)
Every statement is guarded (CREATE ... IF NOT EXISTS, ADD COLUMN IF NOT EXISTS, policy only when missing): production builds
tables with create_all at startup, so this must also repair a table that already exists. Downgrade drops only these.

Revision ID: 171
Revises: 170
Create Date: 2026-10-23
"""
from alembic import op

revision = "171"
down_revision = "170"
branch_labels = None
depends_on = None

TABLE = "lead_evidence_imports"
COLUMNS = (
    ("guest_location", "VARCHAR(100)"),
    ("outcome_reason", "VARCHAR(30)"),
    ("outcome_reason_note", "VARCHAR(300)"),
    ("outcome_reason_source", "VARCHAR(20)"),
    ("outcome_decided_by", "VARCHAR"),
    ("outcome_decided_at", "TIMESTAMP WITH TIME ZONE"),
    ("outcome_proposal", "JSON"),
)


def upgrade():
    bind = op.get_bind()
    pg = bind.dialect.name == "postgresql"
    ts = "TIMESTAMPTZ" if pg else "TIMESTAMP"
    now = "now()" if pg else "CURRENT_TIMESTAMP"
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id               VARCHAR PRIMARY KEY,
            tenant_id        VARCHAR NOT NULL,
            inquiry_id       VARCHAR NOT NULL REFERENCES inquiries(id),
            guest_id         VARCHAR REFERENCES guests(id),
            kind             VARCHAR(20) NOT NULL,
            status           VARCHAR(12) NOT NULL DEFAULT 'done',
            filename         VARCHAR(255),
            uploaded_by      VARCHAR REFERENCES users(id) ON DELETE SET NULL,
            conversation_id  VARCHAR,
            call_id          VARCHAR,
            message_count    INTEGER NOT NULL DEFAULT 0,
            duplicate_count  INTEGER NOT NULL DEFAULT 0,
            media_count      INTEGER NOT NULL DEFAULT 0,
            duration_seconds INTEGER,
            first_at         {ts},
            last_at          {ts},
            detail           JSON,
            error            TEXT,
            created_at       {ts} NOT NULL DEFAULT {now},
            updated_at       {ts} NOT NULL DEFAULT {now}
        )
    """)
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_tenant_id ON {TABLE} (tenant_id)")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_inquiry_id ON {TABLE} (inquiry_id)")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_guest_id ON {TABLE} (guest_id)")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_tenant_inquiry ON {TABLE} (tenant_id, inquiry_id)")

    if pg:
        op.execute("SET LOCAL lock_timeout = '10s'")
        for name, kind in COLUMNS:
            if name == "outcome_decided_by":
                kind = "VARCHAR REFERENCES users(id) ON DELETE SET NULL"
            op.execute(f"ALTER TABLE inquiries ADD COLUMN IF NOT EXISTS {name} {kind}")
        op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies WHERE tablename = '{TABLE}' AND policyname = '{TABLE}_tenant_isolation'
                ) THEN
                    CREATE POLICY {TABLE}_tenant_isolation ON {TABLE}
                    USING (tenant_id = current_setting('app.tenant_id', true)::text);
                END IF;
            END
            $$
        """)
        return
    existing = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(inquiries)")}
    for name, kind in COLUMNS:
        if name not in existing:
            op.execute(f"ALTER TABLE inquiries ADD COLUMN {name} {kind}")


def downgrade():
    bind = op.get_bind()
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
    for name, _ in reversed(COLUMNS):
        if bind.dialect.name == "postgresql":
            op.execute(f"ALTER TABLE inquiries DROP COLUMN IF EXISTS {name}")
        else:
            op.drop_column("inquiries", name)
