"""iCal calendar links between a property and an outside calendar.

One row per link, e.g. "Airbnb" for Caravan #1. Every link has an export URL
(HAIP's own calendar for the property, which the other side subscribes to) and,
optionally, an import URL (the other side's calendar, which HAIP reads). A link
with no import URL is export-only, which is how a Google Calendar is fed.

Imported reservations are stored as BlockedDate rows whose notes start with
"ical:<feed id>:<event uid>", so they can be updated or lifted when the source
calendar changes without touching a block a person created by hand.
"""
from sqlalchemy import Boolean, Column, DateTime, Integer, LargeBinary, String, UniqueConstraint

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
