"""Where a contact first came from, in the channel names the dashboard uses.

Kept free of model imports so the migration and the backfill can use it.
"""
from __future__ import annotations

from typing import Optional

# The ``source`` a caller passes when it resolves a guest -> the channel key used by the dashboard filters.
# A source that is not a channel ("system", empty, unknown text) is deliberately absent: first touch is then UNKNOWN,
# and the dashboard says so instead of inventing one.
CHANNEL_BY_SOURCE = {
    "whatsapp": "whatsapp", "whatsapp_personal": "whatsapp", "personal_bridge": "whatsapp", "campaign": "whatsapp",
    "click_to_wa": "whatsapp", "wa_direct": "whatsapp",
    "instagram": "instagram", "instagram_comment": "instagram", "instagram_dm": "instagram", "meta_ig": "instagram",
    "facebook": "facebook", "meta_fb": "facebook",
    "ivr_call": "call", "dograh_ivr": "call", "call": "call", "phone": "call", "inbound_call": "call", "outbound_call": "call",
    # An inbound call with no ad behind it (InquirySource.ORGANIC_CALL): its own channel on the dashboard, "Organic calls".
    "organic_call": "organic_call",
    "website": "website", "web": "website", "web_form": "website", "web_chat": "website", "google": "website",
    "channel_manager": "other", "manual_booking": "other", "agent_manual": "other", "public_api": "other",
    "google_calendar": "other", "rentalwise": "other", "hostaway": "other", "airbnb": "other", "booking_change_guest": "other",
    "email": "other", "walk_in": "other", "referral": "other", "travel_agent": "other",
    "ota_airbnb": "other", "ota_booking": "other", "ota_vrbo": "other", "ota_mmt": "other", "ota_goibibo": "other",
}

# Identity types that on their own say which channel a contact arrived on.
CHANNEL_BY_IDENTITY_TYPE = {"instagram_user_id": "instagram", "whatsapp_number": "whatsapp"}

UNKNOWN = "unknown"


def channel_for_source(source: Optional[str]) -> Optional[str]:
    return CHANNEL_BY_SOURCE.get((source or "").strip().lower())
