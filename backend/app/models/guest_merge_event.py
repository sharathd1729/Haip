"""Who was merged into whom, what moved, and whether it was undone.

Merging two guests re-points their identities, enquiries, calls, conversations and bookings onto the survivor and soft-deletes the
other. Nothing is deleted, but without a record nobody could tell what moved, or put it back. One row per merge keeps the ids
of everything that moved so the merge can be audited and reversed (identity_resolution.unmerge_guests).
"""
from sqlalchemy import JSON, Column, DateTime, String, Text

from app.core.database import Base
from app.models.base import TenantMixin, TimestampMixin, gen_uuid


class GuestMergeEvent(Base, TimestampMixin, TenantMixin):
    __tablename__ = "guest_merge_events"

    id = Column(String, primary_key=True, default=gen_uuid)
    tenant_id = Column(String, nullable=False, index=True)
    survivor_id = Column(String, nullable=False, index=True)
    deprecated_id = Column(String, nullable=False, index=True)
    actor_user_id = Column(String, nullable=True)           # NULL = automatic (an exact identity match)
    reason = Column(String(40), nullable=False, default="exact_identity_match")   # exact_identity_match | manual
    moved = Column(JSON, nullable=False, default=dict)      # {"identities": [ids], "inquiries": [ids], "calls": [...], ...}
    deprecated_lead_state = Column(JSON, nullable=True)     # the deprecated guest's lead fields before the merge
    survivor_lead_state = Column(JSON, nullable=True)       # the survivor's lead fields before the merge
    unmerged_at = Column(DateTime(timezone=True), nullable=True)
    unmerged_by = Column(String, nullable=True)
    note = Column(Text, nullable=True)
