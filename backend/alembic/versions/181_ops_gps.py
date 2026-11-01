"""Ops GPS (phase 3): trackers, positions, alert episodes, the planned route on an ops file.

New tables gps_devices, gps_positions, gps_alert_episodes (tenant_id NOT NULL; on PostgreSQL row-level security enabled +
forced with the usual tenant policy) and one nullable column ops_files.gps_route. Idempotent (IF NOT EXISTS, guarded
policies) because production runs create_all at startup. Uses ops.read / ops.manage from 178; no new grants.
Positions are kept 90 days (beat gps.purge_positions).

Revision ID: 181
Revises: 180
"""

from alembic import op

revision = "181"
down_revision = "180"
branch_labels = None
depends_on = None

_TS = "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"

_TABLES = {
    "gps_devices": f"""
        id               VARCHAR PRIMARY KEY,
        tenant_id        VARCHAR NOT NULL REFERENCES tenants(id),
        provider         VARCHAR(20) NOT NULL,
        external_id      VARCHAR(64) NOT NULL,
        label            VARCHAR(120),
        property_id      VARCHAR REFERENCES properties(id) ON DELETE SET NULL,
        active           BOOLEAN NOT NULL DEFAULT FALSE,
        last_seen_at     TIMESTAMPTZ,
        last_lat         DOUBLE PRECISION,
        last_lng         DOUBLE PRECISION,
        last_speed_kmh   DOUBLE PRECISION,
        last_heading     DOUBLE PRECISION,
        last_ignition    BOOLEAN,
        last_odometer_km DOUBLE PRECISION,
        {_TS},
        CONSTRAINT uq_gps_devices_external UNIQUE (tenant_id, provider, external_id)
    """,
    "gps_positions": """
        id          VARCHAR PRIMARY KEY,
        tenant_id   VARCHAR NOT NULL REFERENCES tenants(id),
        device_id   VARCHAR NOT NULL REFERENCES gps_devices(id) ON DELETE CASCADE,
        property_id VARCHAR REFERENCES properties(id) ON DELETE SET NULL,
        file_id     VARCHAR REFERENCES ops_files(id) ON DELETE SET NULL,
        at          TIMESTAMPTZ NOT NULL,
        lat         DOUBLE PRECISION NOT NULL,
        lng         DOUBLE PRECISION NOT NULL,
        speed_kmh   DOUBLE PRECISION,
        heading     DOUBLE PRECISION,
        ignition    BOOLEAN,
        odometer_km DOUBLE PRECISION,
        source      VARCHAR(20) NOT NULL,
        received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT uq_gps_positions_device_at UNIQUE (device_id, at)
    """,
    "gps_alert_episodes": f"""
        id        VARCHAR PRIMARY KEY,
        tenant_id VARCHAR NOT NULL REFERENCES tenants(id),
        file_id   VARCHAR NOT NULL REFERENCES ops_files(id) ON DELETE CASCADE,
        rule      VARCHAR(20) NOT NULL,
        started_at TIMESTAMPTZ NOT NULL,
        last_at   TIMESTAMPTZ NOT NULL,
        count     INTEGER NOT NULL DEFAULT 1,
        item_id   VARCHAR REFERENCES ops_items(id) ON DELETE SET NULL,
        ended_at  TIMESTAMPTZ,
        detail    JSON,
        {_TS}
    """,
}

_INDEXES = [
    ("ix_gps_positions_property_at", "gps_positions", "(tenant_id, property_id, at)"),
    ("ix_gps_positions_file_at", "gps_positions", "(file_id, at)"),
    ("ix_gps_positions_at", "gps_positions", "(at)"),
    ("ix_gps_alert_episodes_item", "gps_alert_episodes", "(item_id)"),
]


def upgrade():
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '10s'")
    for table, cols in _TABLES.items():
        op.execute(f"CREATE TABLE IF NOT EXISTS {table} ({cols})")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant_id ON {table} (tenant_id)")
    for name, table, cols in _INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} {cols}")
    # One open episode per trip and rule: a second concurrent ingest cannot raise the same alert twice.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_gps_alert_episodes_open ON gps_alert_episodes (file_id, rule) "
        "WHERE ended_at IS NULL"
    )
    op.execute("ALTER TABLE ops_files ADD COLUMN IF NOT EXISTS gps_route JSON")
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


def downgrade():
    op.execute("ALTER TABLE ops_files DROP COLUMN IF EXISTS gps_route")
    for table in reversed(list(_TABLES)):
        op.execute(f"DROP TABLE IF EXISTS {table}")
