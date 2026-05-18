import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.api.v1.deps import get_current_user
from app.models.user import User
from app.models.conversation import Conversation, Message
from app.schemas.conversation import MessageOut, SendMessageRequest, AIDraftRequest, ConversationOut
from app.workers.tasks.concierge_draft import concierge_draft
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/conversations", tags=["conversations"])

# Maximum length for Idempotency-Key header values
_IDEMPOTENCY_KEY_MAX_LEN = 64
# Deduplication window
_IDEMPOTENCY_WINDOW_HOURS = 24


@router.get("", response_model=List[ConversationOut])
def list_conversations(
    channel: str = None,
    is_open: bool = None,
    limit: int = Query(default=50, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Conversation).filter_by(tenant_id=current_user.tenant_id)
    if channel:
        q = q.filter_by(channel=channel)
    if is_open is not None:
        q = q.filter_by(is_open=is_open)
    return q.order_by(Conversation.last_message_at.desc().nullslast()).limit(limit).all()


@router.get("/{conversation_id}/messages", response_model=List[MessageOut])
def get_messages(
    conversation_id: str,
    limit: int = Query(default=50, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = db.query(Conversation).filter_by(id=conversation_id, tenant_id=current_user.tenant_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return (
        db.query(Message).filter_by(conversation_id=conversation_id)
        .order_by(Message.created_at.asc())
        .limit(limit).all()
    )


@router.post("/{conversation_id}/messages", response_model=MessageOut, status_code=201)
def send_message(
    conversation_id: str,
    body: SendMessageRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Send an outbound message on a conversation.

    Idempotency:
    - Pass `Idempotency-Key: <uuid>` header to enable deduplication.
    - Within a 24-hour window, a second request with the same key returns the
      original message (HTTP 200) instead of creating a duplicate.
    - If the header is absent, no deduplication is applied.
    """
    conv = db.query(Conversation).filter_by(id=conversation_id, tenant_id=current_user.tenant_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # ── Idempotency check ─────────────────────────────────────────────────────
    idempotency_key = _extract_idempotency_key(request)

    if idempotency_key:
        existing = _find_idempotent_message(db, current_user.tenant_id, idempotency_key)
        if existing:
            log.info(
                "send_message_idempotent_hit",
                idempotency_key=idempotency_key,
                original_message_id=existing.id,
            )
            return existing  # 201 → 200 via response_model; caller gets original

    # ── Create new message ────────────────────────────────────────────────────
    msg = Message(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        conversation_id=conversation_id,
        direction="outbound",
        channel=conv.channel,
        body=body.body,
        media_url=body.media_url,
        sender_id=current_user.id,
        sender_name=current_user.name,
        was_approved=True,
        idempotency_key=idempotency_key,  # None if header absent
    )
    db.add(msg)

    conv.last_message_at = datetime.now(timezone.utc).isoformat()
    db.commit()
    db.refresh(msg)

    log.info(
        "send_message_created",
        message_id=msg.id,
        conversation_id=conversation_id,
        has_idempotency_key=idempotency_key is not None,
    )

    # Queue delivery
    from app.workers.tasks.send_whatsapp import send_whatsapp
    send_whatsapp.delay(message_id=msg.id, tenant_id=current_user.tenant_id)
    return msg


@router.post("/{conversation_id}/messages/ai-draft")
def request_ai_draft(
    conversation_id: str,
    body: AIDraftRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = db.query(Conversation).filter_by(id=conversation_id, tenant_id=current_user.tenant_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    draft_id = str(uuid.uuid4())
    concierge_draft.delay(
        message_id=draft_id,
        conversation_id=conversation_id,
        tenant_id=current_user.tenant_id,
    )
    return {"status": "draft_queued", "draft_id": draft_id}


@router.post("/{conversation_id}/messages/{message_id}/approve")
def approve_ai_draft(
    conversation_id: str,
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    msg = db.query(Message).filter_by(
        id=message_id, conversation_id=conversation_id, tenant_id=current_user.tenant_id
    ).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    msg.was_approved = True
    msg.sender_id = current_user.id
    db.commit()

    from app.workers.tasks.send_whatsapp import send_whatsapp
    send_whatsapp.delay(message_id=message_id, tenant_id=current_user.tenant_id)
    return {"status": "approved_and_queued"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_idempotency_key(request: Request) -> str | None:
    """
    Read and validate the Idempotency-Key header.
    Returns None if absent; raises 400 if present but invalid.
    """
    raw = request.headers.get("Idempotency-Key") or request.headers.get("idempotency-key")
    if not raw:
        return None
    key = raw.strip()
    if not key:
        return None
    if len(key) > _IDEMPOTENCY_KEY_MAX_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"Idempotency-Key must be at most {_IDEMPOTENCY_KEY_MAX_LEN} characters.",
        )
    return key


def _find_idempotent_message(db: Session, tenant_id: str, key: str) -> Message | None:
    """
    Return an existing message with this key created in the last 24h, or None.
    Uses string comparison on ISO timestamps (consistent with how created_at is stored).
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=_IDEMPOTENCY_WINDOW_HOURS)).isoformat()
    return (
        db.query(Message)
        .filter(
            Message.tenant_id == tenant_id,
            Message.idempotency_key == key,
            Message.created_at >= cutoff,
        )
        .first()
    )
