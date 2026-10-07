"""Booking add-ons, payment ledger and front-desk fields

New tables stay_addons and stay_payments (tenant_id + row-level security) and
three nullable columns on stays. Production builds tables with create_all at API
startup, which adds no RLS, so this creates each table if missing and then always
enables RLS and the policy. Every statement is idempotent.

Revision ID: 110
Revises: 109
Create Date: 2026-10-07
"""
from alembic import op

revision = "110"
down_revision = "109"
branch_labels = None
depends_on = None

_TABLES = ("stay_addons", "stay_payments", "stay_payment_links")


def upgrade():
    op.execute("ALTER TABLE stays ADD COLUMN IF NOT EXISTS check_in_time VARCHAR(5)")
    op.execute("ALTER TABLE stays ADD COLUMN IF NOT EXISTS check_out_time VARCHAR(5)")
    op.execute("ALTER TABLE stays ADD COLUMN IF NOT EXISTS internal_notes TEXT")

    op.execute("""
        CREATE TABLE IF NOT EXISTS stay_addons (
            id          VARCHAR PRIMARY KEY,
            tenant_id   VARCHAR NOT NULL,
            stay_id     VARCHAR NOT NULL REFERENCES stays(id) ON DELETE CASCADE,
            addon_id    VARCHAR,
            name        VARCHAR(255) NOT NULL,
            quantity    INTEGER NOT NULL DEFAULT 1,
            unit_price  NUMERIC(10, 2) NOT NULL DEFAULT 0,
            notes       TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS stay_payments (
            id          VARCHAR PRIMARY KEY,
            tenant_id   VARCHAR NOT NULL,
            stay_id     VARCHAR NOT NULL REFERENCES stays(id) ON DELETE CASCADE,
            kind        VARCHAR(10) NOT NULL DEFAULT 'payment',
            amount      NUMERIC(12, 2) NOT NULL,
            method      VARCHAR(20) NOT NULL DEFAULT 'upi',
            reference   VARCHAR(120),
            external_id VARCHAR(64),
            paid_on     DATE NOT NULL,
            notes       TEXT,
            created_by  VARCHAR,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("ALTER TABLE stay_payments ADD COLUMN IF NOT EXISTS external_id VARCHAR(64)")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_stay_payments_external
        ON stay_payments (tenant_id, external_id) WHERE external_id IS NOT NULL
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS stay_payment_links (
            id           VARCHAR PRIMARY KEY,
            tenant_id    VARCHAR NOT NULL,
            stay_id      VARCHAR NOT NULL REFERENCES stays(id) ON DELETE CASCADE,
            provider     VARCHAR(20) NOT NULL DEFAULT 'razorpay',
            external_id  VARCHAR(64) NOT NULL,
            short_url    VARCHAR(300) NOT NULL,
            amount       NUMERIC(12, 2) NOT NULL,
            status       VARCHAR(20) NOT NULL DEFAULT 'created',
            expires_at   TIMESTAMPTZ,
            created_by   VARCHAR,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_stay_payment_links_external ON stay_payment_links (external_id)")
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
    op.execute("ALTER TABLE stays DROP COLUMN IF EXISTS internal_notes")
    op.execute("ALTER TABLE stays DROP COLUMN IF EXISTS check_out_time")
    op.execute("ALTER TABLE stays DROP COLUMN IF EXISTS check_in_time")
