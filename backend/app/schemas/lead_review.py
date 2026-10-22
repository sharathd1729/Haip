"""Request bodies for the lead page's Type selector and "Valid enquiry?" card (lead_review_service, migration 169)."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

LeadType = Literal["guest", "b2b", "partner"]


class LeadTypeIn(BaseModel):
    lead_type: LeadType


class ValidationIn(BaseModel):
    """A person's review. ``valid`` None clears the review (the enquiry is "not yet reviewed" again)."""
    valid: Optional[bool] = None
    dates_confirmed: Optional[bool] = None
    budget_fits: Optional[bool] = None
    clear_intent: Optional[bool] = None
    note: Optional[str] = Field(default=None, max_length=300)
