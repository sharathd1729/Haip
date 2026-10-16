from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class WhatsAppPersonalSessionOut(BaseModel):
    id: str
    status: str
    phone_number: Optional[str] = None
    agent_name: Optional[str] = None  # populated by the directory list endpoint only
    # Only ever populated on the self-view (GET /sessions/me) while status
    # is pending_pairing -- the latest rotated code, refreshed roughly
    # every 20-30s by the bridge, so the frontend keeps showing a QR that
    # actually still works instead of one that's silently gone stale.
    qr_code_data_url: Optional[str] = None
    last_seen_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class WhatsAppPersonalPairingIn(BaseModel):
    """Optional body for POST /whatsapp-personal/sessions. When
    phone_number is given, pairing uses WhatsApp's phone-number-entry code
    flow instead of a QR scan."""
    phone_number: Optional[str] = None


class WhatsAppPersonalPairingOut(BaseModel):
    """Returned once, immediately after starting/restarting pairing --
    never persisted or re-fetchable, matching how a WhatsApp Web QR/pairing
    code itself is single-use and expires quickly. Exactly one of
    qr_code_data_url/pairing_code is populated, depending on which flow
    was requested."""
    session_id: str
    qr_code_data_url: Optional[str] = None  # "data:image/png;base64,..."
    pairing_code: Optional[str] = None  # e.g. "ABCD-1234"
    status: str


class WhatsAppPersonalInboundMessageIn(BaseModel):
    """Posted by the bridge service for every message it sees on a paired personal number: guest messages, the agent's own
    replies, group messages, and (with ``history``) older messages WhatsApp hands over when the phone is linked. Auth is a
    per-session secret, not JWT -- see webhooks_whatsapp_personal.py.

    The first five fields are the original contract (kept so an older bridge keeps working); everything after is optional."""
    bridge_message_id: str
    from_phone: str = ""              # 1:1 chat: the OTHER person's number (both directions). Group: the sender's number.
    from_name: Optional[str] = None   # the other person's / the group sender's WhatsApp name
    body: str = ""
    occurred_at: Optional[datetime] = None
    chat_jid: Optional[str] = None    # WhatsApp's id of the chat ("...@s.whatsapp.net", "...@g.us", "...@lid")
    chat_type: str = "user"           # "user" | "group"
    chat_name: Optional[str] = None   # group subject / contact name
    direction: str = "inbound"        # "inbound" | "outbound" (the agent's own message)
    history: bool = False             # older message: never a push, a lead or an AI draft
    media_kind: Optional[str] = None  # image | video | audio | document | sticker
    media_mime: Optional[str] = None
    media_filename: Optional[str] = None
    media_base64: Optional[str] = None  # the file itself; the backend stores it in object storage (Cloudflare R2)
    media_skipped: Optional[str] = None  # why the file was not sent ("too_large", "download_failed")


class WhatsAppPersonalHistoryIn(BaseModel):
    """A batch of older messages from the history WhatsApp sends right after linking (no media files)."""
    messages: list[WhatsAppPersonalInboundMessageIn]


class WhatsAppPersonalStatusUpdateIn(BaseModel):
    """Posted by the bridge whenever a session's connection state changes --
    QR (re)generated, paired successfully, disconnected, or logged out."""
    status: str
    phone_number: Optional[str] = None
    device_jid: Optional[str] = None
    qr_code_data_url: Optional[str] = None
