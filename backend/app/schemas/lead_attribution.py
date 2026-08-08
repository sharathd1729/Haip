"""Ad-attribution — Pydantic schemas (Dashboard Metrics Plan Phase 1)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class LeadAttributionSchema(BaseModel):
    id: str
    inquiry_id: Optional[str] = None
    conversation_id: str
    guest_id: str
    destination_channel: str
    ad_id: Optional[str] = None
    adset_id: Optional[str] = None
    campaign_id: Optional[str] = None
    source_type: Optional[str] = None
    headline: Optional[str] = None
    first_message_at: datetime

    class Config:
        from_attributes = True


class ChannelAttributionRow(BaseModel):
    destination_channel: str
    lead_count: int
    ad_id_count: int  # distinct ad_ids that produced at least one lead


class ChannelAttributionResponse(BaseModel):
    period_days: int
    total_attributed_leads: int
    channels: list[ChannelAttributionRow] = []
