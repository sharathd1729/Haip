"""
One-click execution of an AI recommendation — schemas.

Every "AI suggested this, do it" button across the product (Leads360, Calls
Intelligence, Guest Journey, Inbox) posts this same shape to a single endpoint,
rather than each surface inventing its own execute route. The action itself is
run by the existing shared dispatcher in workers/tasks/automation_engine.py, so
one-click execution, automation rules, and the Flow Builder all do the same
thing for a given action — there is one implementation per action, not three.
"""
from typing import Any, Optional

from pydantic import BaseModel, Field


class EntityRefs(BaseModel):
    """What the recommendation is about. At least one must be set."""

    guest_id:    Optional[str] = None
    inquiry_id:  Optional[str] = None
    call_id:     Optional[str] = None
    property_id: Optional[str] = None

    def is_empty(self) -> bool:
        return not any((self.guest_id, self.inquiry_id, self.call_id, self.property_id))

    def primary(self) -> tuple[str, str]:
        """(target_type, target_id) for the audit row — most specific first."""
        for kind, value in (
            ("call", self.call_id),
            ("inquiry", self.inquiry_id),
            ("guest", self.guest_id),
            ("property", self.property_id),
        ):
            if value:
                return kind, value
        return "unknown", ""


class ExecuteActionRequest(BaseModel):
    action_type:   str = Field(..., max_length=40)
    entity_refs:   EntityRefs
    action_config: dict[str, Any] = Field(default_factory=dict)

    # Free-text provenance: which surface/agent proposed this. Recorded on the
    # audit row so an executed action can be traced back to what suggested it.
    source: Optional[str] = Field(None, max_length=60)


class ExecuteActionResponse(BaseModel):
    status: str            # "success" | "failed"
    action_type: str
    detail: str            # human-readable result from the action handler
    audit_id: Optional[str] = None
