"""Test helper: a guest message a minute ago, so WhatsApp's 24-hour window is open for an outbound send
(conversations.send_message refuses free text outside it, as Meta does)."""
import uuid
from datetime import datetime, timedelta, timezone

from app.models.conversation import Message


def open_window(db, conv) -> None:
    db.add(Message(id=str(uuid.uuid4()), tenant_id=conv.tenant_id, conversation_id=conv.id, direction="inbound",
                   channel=conv.channel, body="Hi", created_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
