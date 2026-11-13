"""Channel manager via Channex (services/channex_service.py, adapters/pms/channex.py).

channex_mappings: one row per HAIP unit (properties.id) linked to a Channex property, room type and rate plan; unique per
(tenant, property) and per (tenant, Channex room type). channex_booking_links: one row per Channex booking, tying it to
the HAIP Stay it became, with the last revision applied (a revision applied twice is a no-op). tenant_id + forced RLS on
both. The connection itself is an integrations row (kind "channex", encrypted API key), no schema change.
Idempotent (IF NOT EXISTS, guarded policies) because production runs create_all at startup.

Revision ID: 205
Revises: 204
"""
from alembic import op

revision = "205"
down_revision = "204"
branch_labels = None
depends_on = None

_TABLES = ("channex_mappings", "channex_booking_links")


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS channex_mappings (
            id                   VARCHAR PRIMARY KEY,
            tenant_id            VARCHAR NOT NULL REFERENCES tenants(id),
            property_id          VARCHAR NOT NULL REFERENCES properties(id),
            channex_property_id  VARCHAR(64) NOT NULL,
            channex_room_type_id VARCHAR(64) NOT NULL,
            channex_rate_plan_id VARCHAR(64),
            push_rates           BOOLEAN NOT NULL DEFAULT FALSE,
            last_pushed_at       TIMESTAMPTZ,
            last_push_error      TEXT,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_channex_mappings_property UNIQUE (tenant_id, property_id),
            CONSTRAINT uq_channex_mappings_room_type UNIQUE (tenant_id, channex_room_type_id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS channex_booking_links (
            id                 VARCHAR PRIMARY KEY,
            tenant_id          VARCHAR NOT NULL REFERENCES tenants(id),
            channex_booking_id VARCHAR(64) NOT NULL,
            stay_id            VARCHAR REFERENCES stays(id),
            last_revision_id   VARCHAR(64),
            status             VARCHAR(20),
            ota_name           VARCHAR(80),
            ota_reservation_code VARCHAR(120),
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_channex_booking_links_booking UNIQUE (tenant_id, channex_booking_id)
        )
    """)
    for t in _TABLES:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{t}_tenant_id ON {t} (tenant_id)")
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = '{t}' AND policyname = '{t}_tenant_isolation') THEN
                    CREATE POLICY {t}_tenant_isolation ON {t}
                    USING (tenant_id = current_setting('app.tenant_id', true)::text);
                END IF;
            END
            $$
        """)


def downgrade():
    for t in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t}")
