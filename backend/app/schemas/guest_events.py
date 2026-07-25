"""
Guest event ledger — schemas.

`guest_events` is the append-only, guest-level activity ledger that unifies
what used to be assembled ad hoc per feature (see leads_service.build_timeline,
which unioned messages + calls + inquiry_stage_log in Python on every request).

Event type taxonomy — `<entity>.<past-tense verb>`. Keep this list closed;
add new members here rather than passing free-form strings at call sites.
"""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Event taxonomy ────────────────────────────────────────────────────────────

class GuestEventType:
    """Canonical event_type values. Not an Enum: stored as plain strings so a
    forgotten migration can never break reads of historical rows."""

    MESSAGE_RECEIVED   = "message.received"
    MESSAGE_SENT       = "message.sent"

    CALL_COMPLETED     = "call.completed"
    CALL_ANALYZED      = "call.analyzed"

    INQUIRY_CREATED    = "inquiry.created"
    INQUIRY_STAGE_MOVED = "inquiry.stage_moved"
    INQUIRY_MERGED     = "inquiry.merged"

    AUTOMATION_EXECUTED = "automation.executed"
    AI_SUMMARY_UPDATED  = "ai.summary_updated"


class SourceModule:
    """Which module produced the event — used for per-module filtering."""

    INBOX      = "inbox"
    CALLS      = "calls"
    LEADS360   = "leads360"
    AUTOMATION = "automation"
    AI         = "ai"
    SYSTEM     = "system"


# ── I/O schemas ───────────────────────────────────────────────────────────────

class GuestEventCreate(BaseModel):
    """Input to guest_events_service.record_event()."""

    guest_id:      Optional[str] = None
    inquiry_id:    Optional[str] = None

    entity_type:   str = Field(..., max_length=30)   # message | call | inquiry | automation_run
    entity_id:     str = Field(..., max_length=64)
    event_type:    str = Field(..., max_length=40)
    source_module: str = Field(..., max_length=20)

    occurred_at:   datetime
    channel:       Optional[str] = Field(None, max_length=20)   # whatsapp | instagram | call | system
    direction:     Optional[str] = Field(None, max_length=20)   # inbound | outbound | system
    preview:       Optional[str] = None                          # short human-readable line
    actor_user_id: Optional[str] = None
    is_ai_generated: bool = False
    payload:       dict[str, Any] = Field(default_factory=dict)


class GuestEventSchema(BaseModel):
    """A single ledger row as returned by the service."""

    id:            str
    guest_id:      Optional[str] = None
    inquiry_id:    Optional[str] = None
    entity_type:   str
    entity_id:     str
    event_type:    str
    source_module: str
    occurred_at:   datetime
    channel:       Optional[str] = None
    direction:     Optional[str] = None
    preview:       Optional[str] = None
    actor_user_id: Optional[str] = None
    is_ai_generated: bool = False
    payload:       dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True
