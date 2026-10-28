"""Ops phase 2, readiness and fleet: papers with expiry, defects, scheduled services, onboard inventory, the automatic trip
messages log, the guest ID form, and staff_profiles.last_inbound_at (their 24-hour WhatsApp window).

New tables have tenant_id NOT NULL and, on PostgreSQL, row-level security enabled + forced with the usual tenant policy.
Idempotent (IF NOT EXISTS, guarded policies) because production runs create_all at startup. Uses the ops.read / ops.write /
ops.manage capabilities from 178; no new grants.

ops_guest_form_lookup(token_hash) is SECURITY DEFINER (like website_host_lookup in 158): the guest's form link carries no
tenant, so the hash -> (form, tenant) step runs without RLS and returns only those two ids; every later read sets the tenant
context and goes through RLS.

Revision ID: 180
Revises: 179
"""

from alembic import op

revision = "180"
down_revision = "179"
branch_labels = None
depends_on = None

_TS = "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"

_TABLES = {
    "ops_papers": f"""
        id          VARCHAR PRIMARY KEY,
        tenant_id   VARCHAR NOT NULL REFERENCES tenants(id),
        property_id VARCHAR REFERENCES properties(id),
        staff_id    VARCHAR REFERENCES staff_profiles(id) ON DELETE CASCADE,
        kind        VARCHAR(20) NOT NULL,
        name        VARCHAR(120) NOT NULL,
        number      VARCHAR(60),
        expires_on  DATE,
        file_key    VARCHAR,
        active      BOOLEAN NOT NULL DEFAULT TRUE,
        created_by  VARCHAR,
        {_TS}
    """,
    "ops_defects": f"""
        id          VARCHAR PRIMARY KEY,
        tenant_id   VARCHAR NOT NULL REFERENCES tenants(id),
        property_id VARCHAR NOT NULL REFERENCES properties(id),
        title       VARCHAR(200) NOT NULL,
        detail      TEXT,
        severity    VARCHAR(10) NOT NULL DEFAULT 'normal',
        status      VARCHAR(10) NOT NULL DEFAULT 'open',
        source      VARCHAR(10) NOT NULL DEFAULT 'person',
        file_id     VARCHAR REFERENCES ops_files(id) ON DELETE SET NULL,
        item_key    VARCHAR(40),
        block_id    VARCHAR,
        reported_by VARCHAR,
        closed_at   TIMESTAMPTZ,
        closed_by   VARCHAR,
        close_note  TEXT,
        {_TS}
    """,
    "ops_services": f"""
        id          VARCHAR PRIMARY KEY,
        tenant_id   VARCHAR NOT NULL REFERENCES tenants(id),
        property_id VARCHAR NOT NULL REFERENCES properties(id),
        name        VARCHAR(120) NOT NULL,
        due_on      DATE,
        due_km      INTEGER,
        status      VARCHAR(10) NOT NULL DEFAULT 'open',
        done_on     DATE,
        done_km     INTEGER,
        note        TEXT,
        created_by  VARCHAR,
        done_by     VARCHAR,
        {_TS}
    """,
    "ops_inventory_items": f"""
        id          VARCHAR PRIMARY KEY,
        tenant_id   VARCHAR NOT NULL REFERENCES tenants(id),
        property_id VARCHAR NOT NULL REFERENCES properties(id),
        name        VARCHAR(80) NOT NULL,
        par         INTEGER NOT NULL,
        count       INTEGER,
        counted_at  TIMESTAMPTZ,
        counted_by  VARCHAR,
        {_TS},
        CONSTRAINT uq_ops_inventory_items_name UNIQUE (tenant_id, property_id, name)
    """,
    "ops_auto_messages": f"""
        id        VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        file_id   VARCHAR NOT NULL REFERENCES ops_files(id) ON DELETE CASCADE,
        kind      VARCHAR(20) NOT NULL,
        recipient VARCHAR(80) NOT NULL,
        status    VARCHAR(10) NOT NULL,
        via       VARCHAR(10),
        reason    TEXT,
        attempts  INTEGER NOT NULL DEFAULT 1,
        sent_at   TIMESTAMPTZ,
        {_TS},
        CONSTRAINT uq_ops_auto_messages_once UNIQUE (file_id, kind, recipient)
    """,
    "ops_guest_forms": f"""
        id              VARCHAR PRIMARY KEY,
        tenant_id       VARCHAR NOT NULL REFERENCES tenants(id),
        file_id         VARCHAR NOT NULL REFERENCES ops_files(id) ON DELETE CASCADE,
        stay_id         VARCHAR NOT NULL REFERENCES stays(id) ON DELETE CASCADE,
        nonce           VARCHAR(32) NOT NULL,
        token_hash      VARCHAR(64) NOT NULL,
        data            JSON,
        signed_name     VARCHAR(80),
        consent_version VARCHAR(20),
        submitted_at    TIMESTAMPTZ,
        {_TS},
        CONSTRAINT uq_ops_guest_forms_file UNIQUE (file_id),
        CONSTRAINT uq_ops_guest_forms_token UNIQUE (token_hash)
    """,
}

_LOOKUP_FN = """
CREATE OR REPLACE FUNCTION ops_guest_form_lookup(p_hash text)
RETURNS TABLE (form_id text, tenant_id text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT f.id::text, f.tenant_id::text FROM ops_guest_forms f WHERE f.token_hash = p_hash LIMIT 1 $$
"""

_INDEXES = [
    ("ix_ops_papers_owner", "ops_papers", "(tenant_id, property_id, staff_id)"),
    ("ix_ops_defects_open", "ops_defects", "(tenant_id, property_id, status)"),
    ("ix_ops_services_property", "ops_services", "(tenant_id, property_id)"),
    ("ix_ops_auto_messages_file", "ops_auto_messages", "(file_id)"),
]


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
        op.execute("ALTER TABLE staff_profiles ADD COLUMN IF NOT EXISTS last_inbound_at TIMESTAMPTZ")
    else:
        cols = {r[1] for r in bind.exec_driver_sql("PRAGMA table_info(staff_profiles)")}
        if "last_inbound_at" not in cols:
            op.execute("ALTER TABLE staff_profiles ADD COLUMN last_inbound_at TIMESTAMP")
    for table, cols in _TABLES.items():
        op.execute(f"CREATE TABLE IF NOT EXISTS {table} ({cols})")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)")
    for name, table, cols in _INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} {cols}")
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
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS ops_guest_form_lookup(text)")
    for table in reversed(list(_TABLES)):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE staff_profiles DROP COLUMN IF EXISTS last_inbound_at")
