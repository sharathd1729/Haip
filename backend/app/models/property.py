from sqlalchemy import Column, String, Boolean, JSON, ForeignKey, Text, Integer, Numeric
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid


class Property(Base, TimestampMixin, TenantMixin):
    __tablename__ = "properties"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)

    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False, index=True)
    # villa / resort / hotel / caravan / rental_apartment / travel / other
    type = Column(String(50), default="villa")
    is_active = Column(Boolean, default=True)

    # Location
    address = Column(Text, nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    country = Column(String(10), default="IN")
    lat = Column(Numeric(9, 6), nullable=True)
    lng = Column(Numeric(9, 6), nullable=True)

    # Capacity (villa / resort / rental_apartment)
    max_adults = Column(Integer, default=2)
    max_children = Column(Integer, default=0)
    bedrooms = Column(Integer, default=1)
    bathrooms = Column(Integer, default=1)

    # ── Caravan / glamping specific ───────────────────────────────────────────
    vehicle_name = Column(String(255), nullable=True)          # "Ratha Caravan #1"
    vehicle_type = Column(String(50), nullable=True)           # luxury_caravan / campervan / glamping_pod / sleeper_bus
    home_base = Column(String(100), nullable=True)             # city where vehicle is parked/stationed
    routes = Column(JSON, default=list)                        # [{"from":"Goa","to":"Coorg","km":420}]
    price_per_day = Column(Numeric(10, 2), nullable=True)
    price_per_km = Column(Numeric(6, 2), nullable=True)
    driver_included = Column(Boolean, default=True)
    seats = Column(Integer, nullable=True)                     # passenger capacity

    # IVR
    ivr_virtual_number = Column(String(20), nullable=True)
    ivr_flow_id = Column(String(100), nullable=True)  # CallerDesk/Acefone flow ID

    # Channel manager
    hostaway_listing_id = Column(String(100), nullable=True)
    airbnb_listing_id = Column(String(100), nullable=True)
    channel_manager_listing_id = Column(String(100), nullable=True)  # generic (retalwise, staah, etc.)
    channel_source = Column(String(50), nullable=True)               # hostaway / retalwise / airbnb / booking

    # Amenities + media
    amenities = Column(JSON, default=list)
    photos = Column(JSON, default=list)
    description = Column(Text, nullable=True)

    # Brand
    brand_voice = Column(Text, nullable=True)
    faqs = Column(JSON, default=list)

    tenant = relationship("Tenant", back_populates="properties")
    rate_plans = relationship("RatePlan", back_populates="property", lazy="dynamic")
    stays = relationship("Stay", back_populates="property", lazy="dynamic")
    rooms = relationship("Room", back_populates="property", lazy="dynamic")


class Room(Base, TimestampMixin, TenantMixin):
    """Individual rooms inside a hotel / boutique property."""
    __tablename__ = "rooms"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    property_id = Column(String, ForeignKey("properties.id"), nullable=False, index=True)

    room_number = Column(String(20), nullable=False)      # "101", "Suite A", "Penthouse"
    room_type = Column(String(50), default="standard")    # standard / deluxe / suite / penthouse / dormitory
    floor = Column(Integer, nullable=True)
    capacity = Column(Integer, default=2)                 # max guests
    amenities = Column(JSON, default=list)               # ["AC","TV","balcony"]
    is_active = Column(Boolean, default=True)

    property = relationship("Property", back_populates="rooms")


class RatePlan(Base, TimestampMixin, TenantMixin):
    __tablename__ = "rate_plans"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    property_id = Column(String, ForeignKey("properties.id"), nullable=False, index=True)

    name = Column(String(255), nullable=False)
    base_price_per_night = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default="INR")
    min_nights = Column(Integer, default=1)
    max_nights = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True)

    # Seasonal overrides
    seasonal_pricing = Column(JSON, default=list)  # [{from, to, price}]
    inclusions = Column(JSON, default=list)         # breakfast, airport-transfer, etc.

    property = relationship("Property", back_populates="rate_plans")


class Stay(Base, TimestampMixin, TenantMixin):
    __tablename__ = "stays"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    guest_id = Column(String, ForeignKey("guests.id"), nullable=False, index=True)
    property_id = Column(String, ForeignKey("properties.id"), nullable=False, index=True)
    inquiry_id = Column(String, ForeignKey("inquiries.id"), nullable=True)

    check_in = Column(String, nullable=False)   # ISO date
    check_out = Column(String, nullable=False)  # ISO date
    adults = Column(Integer, default=1)
    children = Column(Integer, default=0)

    status = Column(String(30), default="confirmed")  # confirmed/checked_in/checked_out/cancelled
    total_amount = Column(Numeric(12, 2), nullable=True)
    currency = Column(String(3), default="INR")

    special_requests = Column(JSON, default=list)
    dietary_requirements = Column(JSON, default=list)
    occasion = Column(String(100), nullable=True)

    # Channel manager sync
    hostaway_booking_id = Column(String(100), nullable=True)
    channel_source = Column(String(50), nullable=True)  # direct/airbnb/booking/vrbo

    guest = relationship("Guest", back_populates="stays")
    property = relationship("Property", back_populates="stays")
