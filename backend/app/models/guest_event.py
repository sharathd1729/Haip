"""
guest_events — append-only, guest-level activity ledger.

One row per thing that happened to a guest, regardless of which module produced
it. Replaces the per-feature timeline assembly in leads_service.build_timeline()
and is the backing store for the Guest Journey view.

Append-only: rows are never updated or deleted outside of DPDP retention purges.

Idempotency: (tenant_id, entity_type, entity_id, event_type) is unique, so
dual-writing from live code paths and re-running the backfill cannot create
duplicates.
"""
from sqlalchemy import Column, String, Text, Boolean, DateTime, Index, UniqueConstraint, JSON
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base
from app.models.base import TimestampMixin, TenantMixin, gen_uuid


class GuestEvent(Base, TimestampMixin, TenantMixin):
    __tablename__ = "guest_events"

    id            = Column(String, primary_key=True, default=gen_uuid)
    tenant_id     = Column(String, nullable=False, index=True)

    # Nullable: an event can arrive before identity resolution assigns a GID
    # (e.g. an inbound message from an unknown number). Backfilled on merge.
    guest_id      = Column(String, nullable=True, index=True)
    inquiry_id    = Column(String, nullable=True, index=True)

    entity_type   = Column(String(30), nullable=False)   # message | call | inquiry | automation_run
    entity_id     = Column(String(64), nullable=False)
    event_type    = Column(String(40), nullable=False)   # see schemas.guest_events.GuestEventType
    source_module = Column(String(20), nullable=False)   # see schemas.guest_events.SourceModule

    occurred_at   = Column(DateTime(timezone=True), nullable=False)

    # First-class columns for the fields every timeline row needs to render,
    # so the common read path never has to unpack JSON.
    channel         = Column(String(20), nullable=True)
    direction       = Column(String(20), nullable=True)
    preview         = Column(Text, nullable=True)
    actor_user_id   = Column(String, nullable=True)
    is_ai_generated = Column(Boolean, nullable=False, default=False)

    # JSONB on Postgres, generic JSON on SQLite so the test suite can
    # create_all() — same reason as app/models/saved_view.py.
    payload       = Column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "entity_type", "entity_id", "event_type",
            name="uq_guest_events_dedup",
        ),
        Index("ix_guest_events_tenant_guest_time", "tenant_id", "guest_id", "occurred_at"),
        Index("ix_guest_events_tenant_inquiry_time", "tenant_id", "inquiry_id", "occurred_at"),
    )
