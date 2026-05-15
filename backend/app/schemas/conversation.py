from pydantic import BaseModel
from typing import Optional, List


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    direction: str
    channel: str
    body: Optional[str] = None
    media_url: Optional[str] = None
    is_ai_generated: bool = False
    ai_confidence: Optional[float] = None
    was_approved: Optional[bool] = None
    sender_name: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class ConversationOut(BaseModel):
    id: str
    tenant_id: str
    guest_id: str
    inquiry_id: Optional[str] = None
    channel: str
    is_open: bool = True
    ai_mode: Optional[str] = "shadow"
    last_message_at: Optional[str] = None

    class Config:
        from_attributes = True


class SendMessageRequest(BaseModel):
    body: str
    media_url: Optional[str] = None


class AIDraftRequest(BaseModel):
    """Ask the AI concierge to draft a reply for a conversation."""
    context_hint: Optional[str] = None  # optional instruction override
