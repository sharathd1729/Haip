"""Booking payment schedule, security deposit, service requests, concierge notes

Revision ID: 111
Revises: 110
Create Date: 2026-10-08
"""
from alembic import op

revision = "111"
down_revision = "110"
branch_labels = None
depends_on = None

_TABLES = ("stay_instalments", "stay_deposits", "stay_service_requests")


def upgrade():
    op.execute("ALTER TABLE stays ADD COLUMN IF NOT EXISTS concierge_notes TEXT")
    op.execute("""
        CREATE TABLE IF NOT EXISTS stay_instalments (
            id         VARCHAR PRIMARY KEY,
            tenant_id  VARCHAR NOT NULL,
            stay_id    VARCHAR NOT NULL REFERENCES stays(id) ON DELETE CASCADE,
            label      VARCHAR(80) NOT NULL,
            amount     NUMERIC(12, 2) NOT NULL,
            due_date   DATE NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS stay_deposits (
            id           VARCHAR PRIMARY KEY,
            tenant_id    VARCHAR NOT NULL,
            stay_id      VARCHAR NOT NULL UNIQUE REFERENCES stays(id) ON DELETE CASCADE,
            amount       NUMERIC(12, 2) NOT NULL,
            status       VARCHAR(12) NOT NULL DEFAULT 'pending',
            deducted     NUMERIC(12, 2) NOT NULL DEFAULT 0,
            method       VARCHAR(20),
            collected_on DATE,
            resolved_on  DATE,
            notes        TEXT,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS stay_service_requests (
            id           VARCHAR PRIMARY KEY,
            tenant_id    VARCHAR NOT NULL,
            stay_id      VARCHAR NOT NULL REFERENCES stays(id) ON DELETE CASCADE,
            title        VARCHAR(200) NOT NULL,
            notes        TEXT,
            status       VARCHAR(10) NOT NULL DEFAULT 'open',
            assigned_to  VARCHAR,
            due_date     DATE,
            completed_at TIMESTAMPTZ,
            task_id      VARCHAR,
            created_by   VARCHAR,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    for t in _TABLES:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{t}_tenant_id ON {t} (tenant_id)")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{t}_stay_id ON {t} (stay_id)")
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE tablename = '{t}' AND policyname = '{t}_tenant_isolation'
                ) THEN
                    CREATE POLICY {t}_tenant_isolation ON {t}
                    USING (tenant_id = current_setting('app.tenant_id', true)::text);
                END IF;
            END
            $$
        """)


def downgrade():
    for t in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {t}")
    op.execute("ALTER TABLE stays DROP COLUMN IF EXISTS concierge_notes")
