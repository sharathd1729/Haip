"""iCal calendar links between a property and an outside calendar.

One row per link, e.g. "Airbnb" for Caravan #1. Every link has an export URL
(HAIP's own calendar for the property, which the other side subscribes to) and,
optionally, an import URL (the other side's calendar, which HAIP reads). A link
with no import URL is export-only, which is how a Google Calendar is fed.

Imported reservations are stored as BlockedDate rows whose notes start with
"ical:<feed id>:<event uid>", so they can be updated or lifted when the source
calendar changes without touching a block a person created by hand.
"""
from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, LargeBinary, String, UniqueConstraint

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid


class ICalFeed(Base, TimestampMixin, TenantMixin):
    __tablename__ = "ical_feeds"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    property_id = Column(String, nullable=False, index=True)
    name = Column(String(80), nullable=False)                 # "Airbnb", "Booking.com", ...

    # The other side's calendar URL. Treated as a secret (OTA calendar URLs
    # carry an unguessable token), so Fernet-encrypted like other credentials.
    import_url_enc = Column(LargeBinary, nullable=True)

    # Unguessable path token for HAIP's own calendar (the export URL).
    export_token = Column(String(64), nullable=False)

    is_active = Column(Boolean, nullable=False, default=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    last_status = Column(String(20), nullable=True)           # ok | error
    last_error = Column(String(500), nullable=True)
    last_event_count = Column(Integer, nullable=True)
    last_conflicts = Column(Integer, nullable=True)           # imported blocks overlapping a HAIP booking

    __table_args__ = (
        UniqueConstraint("export_token", name="uq_ical_feed_export_token"),
    )


class ICalFeedVehicle(Base, TimestampMixin, TenantMixin):
    """Which vehicle (property) an event in a SHARED calendar belongs to, by name keywords.

    One Google Calendar can hold the bookings of several vehicles. When a link has rows here, an event blocks the
    properties whose keywords appear in its title or description (for example "white" -> Ratha White); an event that
    matches none is ambiguous and blocks every property listed until someone says which vehicle it is. A link with no rows
    behaves as before: everything blocks the link's own property.
    """
    __tablename__ = "ical_feed_vehicles"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    feed_id = Column(String, nullable=False, index=True)
    property_id = Column(String, nullable=False, index=True)
    keywords = Column(JSON, nullable=False, default=list)      # ["white", "white ratha"]

    __table_args__ = (UniqueConstraint("feed_id", "property_id", name="uq_ical_feed_vehicle"),)


class ICalEventDetail(Base, TimestampMixin, TenantMixin):
    """What an imported event said: its title and the booking details read from its description.

    One row per imported block (BlockedDate). Kept in its own table so existing tables are untouched. ``details`` holds
    guest, phone, destination, package and amounts (see ical_event_details.extract); amounts are only shown to roles
    with revenue.read. ``dates_source`` says whether the blocked days came from the description or the event itself;
    ``needs_vehicle`` marks an event that named no vehicle and is blocking all of them.
    """
    __tablename__ = "ical_event_details"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    blocked_date_id = Column(String, nullable=False, unique=True)
    feed_id = Column(String, nullable=False, index=True)
    event_uid = Column(String(255), nullable=False)
    title = Column(String(255), nullable=True)
    details = Column(JSON, nullable=True)
    dates_source = Column(String(12), nullable=False, default="event")      # description | event
    needs_vehicle = Column(Boolean, nullable=False, default=False)


class ICalEventBooking(Base, TimestampMixin, TenantMixin):
    """The booking (Stay) made from one event of a shared calendar, so a later edit or delete of the event updates or
    cancels that booking. ``payment_id`` is the advance recorded from the event, kept so a changed advance is updated in
    place rather than recorded twice."""
    __tablename__ = "ical_event_bookings"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    feed_id = Column(String, nullable=False)
    event_key = Column(String(300), nullable=False)
    stay_id = Column(String, nullable=False, index=True)
    payment_id = Column(String, nullable=True)

    __table_args__ = (UniqueConstraint("feed_id", "event_key", name="uq_ical_event_booking"),)
