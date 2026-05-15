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

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Caravan + channel manager columns on properties ───────────────────────
    op.add_column("properties", sa.Column("vehicle_name", sa.String(255), nullable=True))
    op.add_column("properties", sa.Column("vehicle_type", sa.String(50), nullable=True))
    op.add_column("properties", sa.Column("home_base", sa.String(100), nullable=True))
    op.add_column("properties", sa.Column("routes", sa.JSON(), nullable=True, server_default="'[]'"))
    op.add_column("properties", sa.Column("price_per_day", sa.Numeric(10, 2), nullable=True))
    op.add_column("properties", sa.Column("price_per_km", sa.Numeric(6, 2), nullable=True))
    op.add_column("properties", sa.Column("driver_included", sa.Boolean(), nullable=True, server_default="true"))
    op.add_column("properties", sa.Column("seats", sa.Integer(), nullable=True))
    op.add_column("properties", sa.Column("channel_manager_listing_id", sa.String(100), nullable=True))
    op.add_column("properties", sa.Column("channel_source", sa.String(50), nullable=True))

    # ── Rooms table ───────────────────────────────────────────────────────────
    op.create_table(
        "rooms",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("property_id", sa.String(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("room_number", sa.String(20), nullable=False),
        sa.Column("room_type", sa.String(50), nullable=False, server_default="'standard'"),
        sa.Column("floor", sa.Integer(), nullable=True),
        sa.Column("capacity", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("amenities", sa.JSON(), nullable=True, server_default="'[]'"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.String(), nullable=True),
        sa.Column("updated_at", sa.String(), nullable=True),
    )
    op.create_index("ix_rooms_tenant_id", "rooms", ["tenant_id"])
    op.create_index("ix_rooms_property_id", "rooms", ["property_id"])

    # RLS for rooms
    op.execute("ALTER TABLE rooms ENABLE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY rooms_isolation ON rooms "
        "USING (tenant_id = current_setting('app.tenant_id', true)::text);"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS rooms_isolation ON rooms;")
    op.drop_index("ix_rooms_property_id", table_name="rooms")
    op.drop_index("ix_rooms_tenant_id", table_name="rooms")
    op.drop_table("rooms")

    op.drop_column("properties", "channel_source")
    op.drop_column("properties", "channel_manager_listing_id")
    op.drop_column("properties", "seats")
    op.drop_column("properties", "driver_included")
    op.drop_column("properties", "price_per_km")
    op.drop_column("properties", "price_per_day")
    op.drop_column("properties", "routes")
    op.drop_column("properties", "home_base")
    op.drop_column("properties", "vehicle_type")
    op.drop_column("properties", "vehicle_name")
