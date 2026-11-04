"""Website phase 4: promo codes for website bookings.

  * website_promo_codes (new, tenant_id + forced RLS): code (unique per tenant, upper case), percent | flat, value,
    optional validity dates, minimum nights, usage cap + count, optional property list (empty = every stay), active.
Applied by website_pricing.quote (the nights' rates, so GST is charged on what the guest really pays) and therefore the
Razorpay amount; created and changed by owner/manager, audited. Idempotent (production runs create_all).

Revision ID: 184
Revises: 183
"""

from alembic import op

revision = "184"
down_revision = "183"
branch_labels = None
depends_on = None

_TABLE = "website_promo_codes"
_COLS = """
    id          VARCHAR PRIMARY KEY,
    tenant_id   VARCHAR NOT NULL REFERENCES tenants(id),
    code        VARCHAR(30) NOT NULL,
    kind        VARCHAR(10) NOT NULL,
    value       NUMERIC(12, 2) NOT NULL,
    starts_on   DATE,
    ends_on     DATE,
    min_nights  INTEGER NOT NULL DEFAULT 1,
    max_uses    INTEGER,
    used_count  INTEGER NOT NULL DEFAULT 0,
    property_ids JSON,
    label       VARCHAR(80),
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_by  VARCHAR,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_website_promo_codes_code UNIQUE (tenant_id, code)
"""


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(f"CREATE TABLE IF NOT EXISTS {_TABLE} ({_COLS})")
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_tenant_id ON {_TABLE} (tenant_id)")
    if postgres:
        op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies WHERE tablename = '{_TABLE}' AND policyname = '{_TABLE}_tenant_isolation'
                ) THEN
                    CREATE POLICY {_TABLE}_tenant_isolation ON {_TABLE}
                    USING (tenant_id = current_setting('app.tenant_id', true)::text);
                END IF;
            END
            $$
        """)


def downgrade():
    op.execute(f"DROP TABLE IF EXISTS {_TABLE}")
