from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class WhatsAppPersonalSessionOut(BaseModel):
    id: str
    status: str
    phone_number: Optional[str] = None
    agent_name: Optional[str] = None  # populated by the directory list endpoint only
    last_seen_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class WhatsAppPersonalPairingOut(BaseModel):
    """Returned once, immediately after starting/restarting pairing --
    never persisted or re-fetchable, matching how a WhatsApp Web QR itself
    is single-use and expires in ~60s."""
    session_id: str
    qr_code_data_url: str  # "data:image/png;base64,..."
    status: str


class WhatsAppPersonalInboundMessageIn(BaseModel):
    """Posted by the bridge service for every inbound message it receives
    on a paired personal number. Auth is a per-session secret, not JWT --
    see webhooks_whatsapp_personal.py."""
    bridge_message_id: str
    from_phone: str
    from_name: Optional[str] = None
    body: str = ""
    occurred_at: Optional[datetime] = None


class WhatsAppPersonalStatusUpdateIn(BaseModel):
    """Posted by the bridge whenever a session's connection state changes --
    QR (re)generated, paired successfully, disconnected, or logged out."""
    status: str
    phone_number: Optional[str] = None
    device_jid: Optional[str] = None
    qr_code_data_url: Optional[str] = None
