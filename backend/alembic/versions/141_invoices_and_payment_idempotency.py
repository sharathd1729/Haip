"""Invoices, invoice number series, payment idempotency, payment links that can belong to a quote

* ``invoices`` and ``invoice_sequences`` (tenant_id + row-level security).
* ``stay_payments``: the partial unique index on (tenant_id, external_id) that the Razorpay webhook now relies on.
  110 already creates it, but a database whose table came from create_all before the model declared it has none, and
  duplicates may exist there. Duplicates are not deleted: every copy after the first keeps its amount but loses its
  external_id and gets a note asking staff to review it (then it can be removed like any manual entry). Idempotent.
* ``stay_payment_links``: stay_id becomes nullable and ``inquiry_quote_id`` is added, so a link can belong to a quote
  before any booking exists. A row must have one or the other (check constraint).

Follows 140 (the quote builder: inquiry_quotes options + capabilities); first written on 128 while the two branches were
apart, re-parented when they were merged. 129-139 belong to branches not merged yet. Production builds tables with create_all at startup (no RLS), so every statement is guarded.

Revision ID: 141
Revises: 140
Create Date: 2026-10-18
"""
from alembic import op

revision = "141"
down_revision = "140"
branch_labels = None
depends_on = None

_TABLES = ("invoices", "invoice_sequences")


def _rls(table: str) -> None:
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)")
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
    op.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id              VARCHAR PRIMARY KEY,
            tenant_id       VARCHAR NOT NULL,
            stay_id         VARCHAR REFERENCES stays(id) ON DELETE SET NULL,
            kind            VARCHAR(12) NOT NULL DEFAULT 'invoice',
            number          VARCHAR(40) NOT NULL,
            financial_year  VARCHAR(7) NOT NULL,
            status          VARCHAR(12) NOT NULL DEFAULT 'issued',
            currency        VARCHAR(3) NOT NULL DEFAULT 'INR',
            gst_rate        NUMERIC(5, 2) NOT NULL DEFAULT 0,
            taxable_value   NUMERIC(12, 2) NOT NULL DEFAULT 0,
            cgst            NUMERIC(12, 2) NOT NULL DEFAULT 0,
            sgst            NUMERIC(12, 2) NOT NULL DEFAULT 0,
            igst            NUMERIC(12, 2) NOT NULL DEFAULT 0,
            total           NUMERIC(12, 2) NOT NULL DEFAULT 0,
            amount_received NUMERIC(12, 2) NOT NULL DEFAULT 0,
            balance_due     NUMERIC(12, 2) NOT NULL DEFAULT 0,
            place_of_supply VARCHAR(2),
            lines           JSON NOT NULL DEFAULT '[]',
            seller          JSON NOT NULL DEFAULT '{}',
            buyer           JSON NOT NULL DEFAULT '{}',
            booking_ref     VARCHAR(40),
            pdf_media_key   VARCHAR(300),
            supersedes_id   VARCHAR,
            invoice_id      VARCHAR,
            payment_id      VARCHAR,
            notes           TEXT,
            created_by      VARCHAR,
            issued_at       TIMESTAMPTZ NOT NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_invoices_tenant_number UNIQUE (tenant_id, number)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_invoices_tenant_stay ON invoices (tenant_id, stay_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_invoices_supersedes_id ON invoices (supersedes_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_invoices_payment_id ON invoices (payment_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS invoice_sequences (
            id              VARCHAR PRIMARY KEY,
            tenant_id       VARCHAR NOT NULL,
            financial_year  VARCHAR(7) NOT NULL,
            prefix          VARCHAR(10) NOT NULL,
            next_number     INTEGER NOT NULL DEFAULT 1,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_invoice_sequences_series UNIQUE (tenant_id, financial_year, prefix)
        )
    """)
    for t in _TABLES:
        _rls(t)

    # Payment idempotency: neutralise duplicates first (keep the first copy), then the unique index can exist.
    op.execute("""
        DO $$
        DECLARE n integer;
        BEGIN
            WITH ranked AS (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY tenant_id, external_id ORDER BY created_at, id) AS rn
                FROM stay_payments WHERE external_id IS NOT NULL
            )
            UPDATE stay_payments p
            SET notes = COALESCE(p.notes || ' ', '') || '[Duplicate of Razorpay payment ' || p.external_id
                        || ', recorded twice by a webhook retry. Review it and remove it if the guest paid once.]',
                external_id = NULL
            FROM ranked r WHERE p.id = r.id AND r.rn > 1;
            GET DIAGNOSTICS n = ROW_COUNT;
            IF n > 0 THEN
                RAISE NOTICE 'stay_payments: % duplicate Razorpay payment row(s) flagged for review', n;
            END IF;
        END
        $$
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_stay_payments_external
        ON stay_payments (tenant_id, external_id) WHERE external_id IS NOT NULL
    """)

    # Payment links: a link can belong to a quote (no booking yet).
    op.execute("ALTER TABLE stay_payment_links ALTER COLUMN stay_id DROP NOT NULL")
    op.execute("""
        ALTER TABLE stay_payment_links ADD COLUMN IF NOT EXISTS inquiry_quote_id VARCHAR
        REFERENCES inquiry_quotes(id) ON DELETE SET NULL
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_stay_payment_links_inquiry_quote_id ON stay_payment_links (inquiry_quote_id)")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_stay_payment_links_owner') THEN
                ALTER TABLE stay_payment_links ADD CONSTRAINT ck_stay_payment_links_owner
                CHECK (stay_id IS NOT NULL OR inquiry_quote_id IS NOT NULL);
            END IF;
        END
        $$
    """)


def downgrade():
    op.execute("ALTER TABLE stay_payment_links DROP CONSTRAINT IF EXISTS ck_stay_payment_links_owner")
    op.execute("DROP INDEX IF EXISTS ix_stay_payment_links_inquiry_quote_id")
    # Quote links have no booking to belong to once the column is gone.
    op.execute("DELETE FROM stay_payment_links WHERE stay_id IS NULL")
    op.execute("ALTER TABLE stay_payment_links DROP COLUMN IF EXISTS inquiry_quote_id")
    op.execute("ALTER TABLE stay_payment_links ALTER COLUMN stay_id SET NOT NULL")
    # uq_stay_payments_external belongs to migration 110; it stays.
    for t in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {t}")
