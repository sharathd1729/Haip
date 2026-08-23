from sqlalchemy import Column, String, Boolean, JSON, ForeignKey, Text, Integer, Numeric, Date
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
    addons = relationship("PropertyAddOn", back_populates="property", lazy="dynamic")
    seasonal_rates = relationship("SeasonalRate", back_populates="property", lazy="dynamic")
    blocked_dates = relationship("BlockedDate", back_populates="property", lazy="dynamic")


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

    # Caravan-only bucket: which product this plan prices -- "same_day" /
    # "overnight" / "multiday". NULL for every villa RatePlan (that model
    # is nights-agnostic by design, one plan covers any stay length within
    # min/max_nights). Only ever read when property.type == "caravan"
    # (calculator_service._resolve_rate) -- see migration 087.
    duration_type = Column(String(20), nullable=True)

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

    # Real DATE since migration 071 (Dashboard Metrics Plan F5) -- was a
    # hand-entered-tolerant ISO string. Callers must treat check_in/
    # check_out as datetime.date objects now, not strings -- date.fromisoformat()
    # on a fetched value will raise TypeError; the DB comparisons still
    # accept ISO strings on the query side (Postgres implicitly casts).
    check_in = Column(Date, nullable=False)
    check_out = Column(Date, nullable=False)
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


class PropertyAddOn(Base, TimestampMixin, TenantMixin):
    """
    Add-on services for a property or caravan.
    Examples: candle-lit dinner, airport transfer, private chef, early check-in,
              birthday cake, couples massage, bonfire, guided trek, etc.
    """
    __tablename__ = "property_addons"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    property_id = Column(String, ForeignKey("properties.id"), nullable=False, index=True)

    name = Column(String(255), nullable=False)          # "Candle-lit dinner"
    description = Column(Text, nullable=True)            # shown in quote
    category = Column(String(50), default="experience")  # experience / transfer / meal / stay / other
    price = Column(Numeric(10, 2), nullable=False)
    price_type = Column(String(20), default="per_stay")  # per_stay | per_night | per_person | per_unit
    currency = Column(String(3), default="INR")
    is_active = Column(Boolean, default=True)
    sort_order = Column(Integer, default=0)

    property = relationship("Property", back_populates="addons")


class SeasonalRate(Base, TimestampMixin, TenantMixin):
    """
    Date-range based pricing override for a property.
    Supports: peak season, holiday surcharge, off-season discount.
    Multiple seasonal rates can exist per property — first match wins (ordered by priority).
    """
    __tablename__ = "seasonal_rates"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    property_id = Column(String, ForeignKey("properties.id"), nullable=False, index=True)

    name = Column(String(100), nullable=False)           # "Christmas Peak", "Monsoon Off-season"
    date_from = Column(String(10), nullable=False)        # YYYY-MM-DD
    date_to = Column(String(10), nullable=False)          # YYYY-MM-DD
    price_per_night = Column(Numeric(10, 2), nullable=False)
    min_nights = Column(Integer, default=1)
    currency = Column(String(3), default="INR")
    priority = Column(Integer, default=0)                 # higher wins when ranges overlap
    is_active = Column(Boolean, default=True)

    # Occupancy-based overrides: {4: 95000, 6: 110000}  (guests → price)
    occupancy_pricing = Column(JSON, default=dict)

    property = relationship("Property", back_populates="seasonal_rates")


class BlockedDate(Base, TimestampMixin, TenantMixin):
    """
    Manual date blocks for a property — maintenance, personal use, offline booking.
    When a date range is blocked the property will NOT appear in calculator results
    and will show as 'Blocked' on the portfolio calendar.
    """
    __tablename__ = "blocked_dates"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False, index=True)
    property_id = Column(String, ForeignKey("properties.id"), nullable=False, index=True)

    blocked_from = Column(String(10), nullable=False)   # YYYY-MM-DD (inclusive)
    blocked_to   = Column(String(10), nullable=False)   # YYYY-MM-DD (exclusive — same convention as check_in/out)

    # Why is it blocked?
    reason = Column(String(30), default="maintenance")  # maintenance | personal | offline_booking | other
    notes  = Column(Text, nullable=True)                # free text, e.g. "AC repair"
    is_active = Column(Boolean, default=True)

    property = relationship("Property", back_populates="blocked_dates")
