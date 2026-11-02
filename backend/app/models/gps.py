"""Ops GPS tables (migration 181).

GpsDevice = one tracker, mapped by a manager to a vehicle (property). Its last_* columns are the latest fix, so the live
map is one row per vehicle. A tracker HAIP has not been told about is created inactive with no vehicle: it shows on the
GPS settings page and its positions are not kept until a manager maps it.
GpsPosition = one stored fix; file_id is the ops file the vehicle was on the road for (NULL when parked). Kept 90 days.
GpsAlertEpisode = one stretch of one problem on one trip (services/gps_alerts.py): the alert fires once per episode.
"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid


class GpsDevice(Base, TimestampMixin, TenantMixin):
    __tablename__ = "gps_devices"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    provider = Column(String(20), nullable=False)  # adapters/gps PROVIDERS key
    external_id = Column(String(64), nullable=False)  # IMEI or the provider's device id
    label = Column(String(120), nullable=True)
    property_id = Column(String, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True)
    active = Column(Boolean, nullable=False, default=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)  # time of the latest fix
    last_lat = Column(Float, nullable=True)
    last_lng = Column(Float, nullable=True)
    last_speed_kmh = Column(Float, nullable=True)
    last_heading = Column(Float, nullable=True)
    last_ignition = Column(Boolean, nullable=True)
    last_odometer_km = Column(Float, nullable=True)

    __table_args__ = (UniqueConstraint("tenant_id", "provider", "external_id", name="uq_gps_devices_external"),)


class GpsPosition(Base, TenantMixin):
    __tablename__ = "gps_positions"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    device_id = Column(String, ForeignKey("gps_devices.id", ondelete="CASCADE"), nullable=False)
    property_id = Column(String, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True)
    file_id = Column(String, ForeignKey("ops_files.id", ondelete="SET NULL"), nullable=True)
    at = Column(DateTime(timezone=True), nullable=False)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    speed_kmh = Column(Float, nullable=True)
    heading = Column(Float, nullable=True)
    ignition = Column(Boolean, nullable=True)
    odometer_km = Column(Float, nullable=True)
    source = Column(String(20), nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("device_id", "at", name="uq_gps_positions_device_at"),
        Index("ix_gps_positions_property_at", "tenant_id", "property_id", "at"),
        Index("ix_gps_positions_file_at", "file_id", "at"),
        Index("ix_gps_positions_at", "at"),
    )


class GpsAlertEpisode(Base, TimestampMixin, TenantMixin):
    __tablename__ = "gps_alert_episodes"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    file_id = Column(String, ForeignKey("ops_files.id", ondelete="CASCADE"), nullable=False)
    rule = Column(String(20), nullable=False)  # off_route | halt | overspeed | night | silent
    started_at = Column(DateTime(timezone=True), nullable=False)
    last_at = Column(DateTime(timezone=True), nullable=False)
    count = Column(Integer, nullable=False, default=1)  # positions in a row with the problem
    item_id = Column(String, ForeignKey("ops_items.id", ondelete="SET NULL"), nullable=True)  # set once the alert fired
    ended_at = Column(DateTime(timezone=True), nullable=True)
    detail = Column(JSON, nullable=True)  # where it started, worst value, the detour track while it lasts

    __table_args__ = (
        Index("ix_gps_alert_episodes_item", "item_id"),
        Index(
            "uq_gps_alert_episodes_open",
            "file_id",
            "rule",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
            sqlite_where=text("ended_at IS NULL"),
        ),
    )
