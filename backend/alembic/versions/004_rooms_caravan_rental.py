"""004 rooms table + caravan fields + rental_apartment support

Adds:
- rooms table (hotel room sub-resource)
- caravan-specific columns on properties
- generic channel_manager columns on properties

Revision ID: 004
Revises: 003
Create Date: 2026-05-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return any(c["name"] == column for c in insp.get_columns(table))


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return table in insp.get_table_names()


def _index_exists(index: str, table: str) -> bool:
    bind = op.get_bind()
    insp = inspect(bind)
    return any(i["name"] == index for i in insp.get_indexes(table))


def upgrade() -> None:
    # Kill idle/stale connections that may hold locks on tables we're about to ALTER.
    # Safe at migration time — stale connections come from previous crashed deploys.
    bind = op.get_bind()
    bind.execute(text(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE pid != pg_backend_pid() "
        "AND datname = current_database() "
        "AND state IN ('idle', 'idle in transaction', 'idle in transaction (aborted)')"
    ))

    # ── Caravan + channel manager columns on properties ───────────────────────
    cols_to_add = [
        ("vehicle_name", sa.Column("vehicle_name", sa.String(255), nullable=True)),
        ("vehicle_type", sa.Column("vehicle_type", sa.String(50), nullable=True)),
        ("home_base", sa.Column("home_base", sa.String(100), nullable=True)),
        ("routes", sa.Column("routes", sa.JSON(), nullable=True, server_default=sa.text("'[]'"))),
        ("price_per_day", sa.Column("price_per_day", sa.Numeric(10, 2), nullable=True)),
        ("price_per_km", sa.Column("price_per_km", sa.Numeric(6, 2), nullable=True)),
        ("driver_included", sa.Column("driver_included", sa.Boolean(), nullable=True, server_default="true")),
        ("seats", sa.Column("seats", sa.Integer(), nullable=True)),
        ("channel_manager_listing_id", sa.Column("channel_manager_listing_id", sa.String(100), nullable=True)),
        ("channel_source", sa.Column("channel_source", sa.String(50), nullable=True)),
    ]
    for col_name, col_def in cols_to_add:
        if not _column_exists("properties", col_name):
            op.add_column("properties", col_def)

    # ── Rooms table ───────────────────────────────────────────────────────────
    if not _table_exists("rooms"):
        op.create_table(
            "rooms",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("property_id", sa.String(), sa.ForeignKey("properties.id"), nullable=False),
            sa.Column("room_number", sa.String(20), nullable=False),
            sa.Column("room_type", sa.String(50), nullable=False, server_default=sa.text("'standard'")),
            sa.Column("floor", sa.Integer(), nullable=True),
            sa.Column("capacity", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("amenities", sa.JSON(), nullable=True, server_default=sa.text("'[]'")),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("created_at", sa.String(), nullable=True),
            sa.Column("updated_at", sa.String(), nullable=True),
        )

    if not _index_exists("ix_rooms_tenant_id", "rooms"):
        op.create_index("ix_rooms_tenant_id", "rooms", ["tenant_id"])
    if not _index_exists("ix_rooms_property_id", "rooms"):
        op.create_index("ix_rooms_property_id", "rooms", ["property_id"])

    # RLS for rooms — only ALTER if RLS is not already enabled (avoids lock wait)
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname='rooms' AND relrowsecurity=true) THEN "
        "ALTER TABLE rooms ENABLE ROW LEVEL SECURITY; "
        "END IF; END $$;"
    )
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename='rooms' AND policyname='rooms_isolation') THEN "
        "CREATE POLICY rooms_isolation ON rooms "
        "USING (tenant_id = current_setting('app.tenant_id', true)::text); "
        "END IF; END $$;"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS rooms_isolation ON rooms;")
    if _index_exists("ix_rooms_property_id", "rooms"):
        op.drop_index("ix_rooms_property_id", table_name="rooms")
    if _index_exists("ix_rooms_tenant_id", "rooms"):
        op.drop_index("ix_rooms_tenant_id", table_name="rooms")
    if _table_exists("rooms"):
        op.drop_table("rooms")

    for col in ["channel_source", "channel_manager_listing_id", "seats",
                "driver_included", "price_per_km", "price_per_day",
                "routes", "home_base", "vehicle_type", "vehicle_name"]:
        if _column_exists("properties", col):
            op.drop_column("properties", col)
