"""Guest add-ons (Ops step 3, gap 3): a guest buys the stay property's add-ons from a private link and pays one
Razorpay link.

  * property_addons.needs_approval BOOLEAN NOT NULL DEFAULT FALSE: a person OKs the request before the link is sent
  * property_addons.stay_change VARCHAR(20) NULL: early_check_in | late_check_out | extra_night (availability checked)
  * guest_addon_links: one private link per stay (only the token's SHA-256 is stored, like ops_guest_forms)
  * guest_addon_orders: what the guest picked, its status and the Razorpay link that pays it (the webhook's discriminator)
New tables have tenant_id NOT NULL and, on PostgreSQL, row-level security enabled + forced with the usual tenant policy.
guest_addon_link_lookup(token_hash) is SECURITY DEFINER (like ops_guest_form_lookup in 180): the link carries no tenant,
so the hash -> (link, tenant) step runs without RLS and returns only those two ids.
Idempotent (IF NOT EXISTS, guarded policies) because production runs create_all at startup.

Revision ID: 192
Revises: 191
"""

from alembic import op

revision = "192"
down_revision = "191"
branch_labels = None
depends_on = None

_TS = "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"

_TABLES = {
    "guest_addon_links": f"""
        id          VARCHAR PRIMARY KEY,
        tenant_id   VARCHAR NOT NULL REFERENCES tenants(id),
        stay_id     VARCHAR NOT NULL REFERENCES stays(id) ON DELETE CASCADE,
        nonce       VARCHAR(32) NOT NULL,
        token_hash  VARCHAR(64) NOT NULL,
        {_TS},
        CONSTRAINT uq_guest_addon_links_stay UNIQUE (stay_id),
        CONSTRAINT uq_guest_addon_links_token UNIQUE (token_hash)
    """,
    "guest_addon_orders": f"""
        id              VARCHAR PRIMARY KEY,
        tenant_id       VARCHAR NOT NULL REFERENCES tenants(id),
        stay_id         VARCHAR NOT NULL REFERENCES stays(id) ON DELETE CASCADE,
        items           JSON NOT NULL,
        amount          NUMERIC(10, 2) NOT NULL,
        status          VARCHAR(20) NOT NULL,
        payment_link_id VARCHAR REFERENCES stay_payment_links(id) ON DELETE SET NULL,
        ops_item_id     VARCHAR,
        decided_by      VARCHAR,
        decided_at      TIMESTAMPTZ,
        decline_reason  VARCHAR(200),
        paid_at         TIMESTAMPTZ,
        {_TS},
        CONSTRAINT uq_guest_addon_orders_link UNIQUE (payment_link_id)
    """,
}

_LOOKUP_FN = """
CREATE OR REPLACE FUNCTION guest_addon_link_lookup(p_hash text)
RETURNS TABLE (link_id text, tenant_id text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT l.id::text, l.tenant_id::text FROM guest_addon_links l WHERE l.token_hash = p_hash LIMIT 1 $$
"""

_ADDON_COLS = {"needs_approval": "BOOLEAN NOT NULL DEFAULT FALSE", "stay_change": "VARCHAR(20)"}


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
        for col, ddl in _ADDON_COLS.items():
            op.execute(f"ALTER TABLE property_addons ADD COLUMN IF NOT EXISTS {col} {ddl}")
    else:
        existing = {r[1] for r in bind.exec_driver_sql("PRAGMA table_info(property_addons)")}
        for col, ddl in _ADDON_COLS.items():
            if col not in existing:
                op.execute(f"ALTER TABLE property_addons ADD COLUMN {col} {ddl}")
    for table, cols in _TABLES.items():
        op.execute(f"CREATE TABLE IF NOT EXISTS {table} ({cols})")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_guest_addon_orders_stay ON guest_addon_orders (tenant_id, stay_id)")
    if postgres:
        for table in _TABLES:
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
        op.execute(_LOOKUP_FN)


def downgrade():
    postgres = op.get_bind().dialect.name == "postgresql"
    if postgres:
        op.execute("DROP FUNCTION IF EXISTS guest_addon_link_lookup(text)")
    for table in reversed(list(_TABLES)):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    for col in _ADDON_COLS:
        if postgres:
            op.execute(f"ALTER TABLE property_addons DROP COLUMN IF EXISTS {col}")
        else:
            op.drop_column("property_addons", col)
