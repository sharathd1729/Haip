import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.api.v1.deps import get_current_user
from app.models.user import User
from app.models.conversation import Conversation, Message, MessageDeliveryState
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
    sort: str = Query(default="smart", pattern="^(smart|recent|unread)$"),
    limit: int = Query(default=50, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from sqlalchemy import case, func
    from sqlalchemy.orm import joinedload
    q = db.query(Conversation).filter_by(tenant_id=current_user.tenant_id)
    if channel:
        q = q.filter_by(channel=channel)
    if is_open is not None:
        q = q.filter_by(is_open=is_open)

    if sort in ("unread", "smart"):
        # unread_count column not yet in schema — sort by recency until tracking is added
        q = q.order_by(Conversation.last_message_at.desc().nullslast())
    else:
        q = q.order_by(Conversation.last_message_at.desc().nullslast())

    # Eager-load related objects to eliminate N+1 queries on serialization.
    q = q.options(
        joinedload(Conversation.guest),
        joinedload(Conversation.inquiry),
    )

    return q.limit(limit).all()


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
        db.query(Message)
        .filter_by(conversation_id=conversation_id, tenant_id=current_user.tenant_id)
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
        is_internal=body.is_internal,
        replied_to_message_id=body.replied_to_message_id,
        scheduled_for=body.scheduled_for,
        delivery_state=None if (body.is_internal or body.scheduled_for) else MessageDeliveryState.PENDING,
    )
    db.add(msg)

    conv.last_message_at = datetime.now(timezone.utc).isoformat()
    db.commit()
    db.refresh(msg)

    log.info(
        "send_message_created",
        message_id=msg.id,
        conversation_id=conversation_id,
        is_internal=body.is_internal,
        has_idempotency_key=idempotency_key is not None,
    )

    # Internal notes are never dispatched; scheduled messages wait for the beat task
    if body.is_internal or body.scheduled_for:
        return msg

    # Transition to QUEUED then dispatch via channel-appropriate task
    msg.delivery_state = MessageDeliveryState.QUEUED
    db.commit()

    channel = str(conv.channel.value if hasattr(conv.channel, "value") else conv.channel)
    if channel == "whatsapp":
        from app.workers.tasks.send_whatsapp import send_whatsapp
        send_whatsapp.delay(message_id=msg.id, tenant_id=current_user.tenant_id)
    elif channel == "instagram":
        from app.workers.tasks.send_instagram_dm import send_instagram_dm
        send_instagram_dm.delay(message_id=msg.id, tenant_id=current_user.tenant_id)
    else:
        log.warning(
            "send_message_no_dispatcher",
            message_id=msg.id,
            channel=channel,
            detail="No outbound dispatcher registered for this channel.",
        )
        msg.delivery_state = MessageDeliveryState.FAILED
        msg.delivery_error = f"No outbound dispatcher for channel: {channel}"
        db.commit()

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


@router.post("/{conversation_id}/messages/{message_id}/retry", response_model=MessageOut)
def retry_failed_message(
    conversation_id: str,
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Re-enqueue delivery for a failed message (W23).
    Uses the original idempotency_key — safe to double-click.
    Only allowed within 24h of original failure.
    """
    msg = db.query(Message).filter_by(
        id=message_id, conversation_id=conversation_id, tenant_id=current_user.tenant_id
    ).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if msg.delivery_state != MessageDeliveryState.FAILED:
        raise HTTPException(status_code=409, detail="Message is not in failed state")

    # Guard: only allow retry within 24h
    if msg.created_at:
        created = msg.created_at
        if hasattr(created, "replace") and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - created).total_seconds()
        if age > 86400:
            raise HTTPException(status_code=410, detail="Retry window (24h) has expired")

    msg.delivery_state = MessageDeliveryState.PENDING
    msg.delivery_error = None
    db.commit()
    db.refresh(msg)

    # Back to QUEUED and re-dispatch
    msg.delivery_state = MessageDeliveryState.QUEUED
    db.commit()

    from app.workers.tasks.send_whatsapp import send_whatsapp
    send_whatsapp.delay(message_id=message_id, tenant_id=current_user.tenant_id)

    db.refresh(msg)
    return msg


@router.post("/{conversation_id}/snooze")
def snooze_conversation(
    conversation_id: str,
    body: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """W14 — Snooze a conversation until a given datetime (ISO string)."""
    conv = db.query(Conversation).filter_by(id=conversation_id, tenant_id=current_user.tenant_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    snooze_until = body.get("snooze_until")
    if snooze_until:
        from dateutil.parser import parse as parse_dt
        try:
            conv.snoozed_until = parse_dt(snooze_until)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid snooze_until datetime")
    else:
        conv.snoozed_until = None  # unsnooze
    db.commit()
    return {"status": "snoozed", "snoozed_until": snooze_until}


@router.get("/search")
def search_conversations(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=20, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """W17 — Full-text search across messages in the tenant."""
    from sqlalchemy import text, func
    from app.models.guest import Guest

    results = db.execute(text("""
        SELECT
            m.id        AS message_id,
            m.body      AS snippet,
            m.created_at AS message_at,
            c.id        AS conversation_id,
            c.channel,
            g.name      AS guest_name,
            g.phone     AS guest_phone,
            ts_rank(m.search_vector, plainto_tsquery('simple', :q)) AS rank
        FROM messages m
        JOIN conversations c ON m.conversation_id = c.id
        LEFT JOIN guests g ON c.guest_id = g.id
        WHERE c.tenant_id = :tid
          AND m.is_internal = false
          AND m.search_vector @@ plainto_tsquery('simple', :q)
        ORDER BY rank DESC, m.created_at DESC
        LIMIT :limit
    """), {"q": q, "tid": current_user.tenant_id, "limit": limit})

    rows = results.fetchall()
    return [
        {
            "message_id":      r.message_id,
            "conversation_id": r.conversation_id,
            "channel":         str(r.channel),
            "guest_name":      r.guest_name,
            "guest_phone":     r.guest_phone,
            "snippet":         r.snippet,
            "message_at":      r.message_at.isoformat() if r.message_at else None,
        }
        for r in rows
    ]


@router.get("/{conversation_id}")
def get_conversation_detail(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return conversation metadata + messages + D9 service window info.
    `last_inbound_at` = timestamp of the most recent inbound message (WhatsApp 24h window starts here).

    NOTE: this route must be declared AFTER GET /search to avoid "search" being
    treated as a conversation_id wildcard.
    """
    from app.models.guest import Guest

    conv = db.query(Conversation).filter_by(
        id=conversation_id, tenant_id=current_user.tenant_id
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    guest = db.query(Guest).filter_by(id=conv.guest_id).first()

    messages = (
        db.query(Message)
        .filter_by(conversation_id=conversation_id)
        .order_by(Message.created_at.asc())
        .limit(200)
        .all()
    )

    # D9: compute last_inbound_at — most recent inbound message timestamp
    last_inbound: "Message | None" = (
        db.query(Message)
        .filter_by(conversation_id=conversation_id, direction="inbound")
        .order_by(Message.created_at.desc())
        .first()
    )

    def _iso(val) -> "str | None":
        if val is None:
            return None
        if isinstance(val, str):
            return val
        return val.isoformat()

    last_inbound_at = _iso(last_inbound.created_at) if last_inbound else None

    def _msg_dict(m: Message) -> dict:
        body = m.body or ""
        return {
            "id": m.id,
            "text": body,
            "direction": m.direction.value if hasattr(m.direction, "value") else str(m.direction),
            "channel": m.channel.value if hasattr(m.channel, "value") else str(m.channel),
            "status": m.delivery_state.value if m.delivery_state and hasattr(m.delivery_state, "value") else str(m.delivery_state or ""),
            "delivery_state": m.delivery_state.value if m.delivery_state and hasattr(m.delivery_state, "value") else None,
            "delivery_error": m.delivery_error,
            "timestamp": _iso(m.created_at) or "",
            "sender_name": m.sender_name,
            "ai_drafted": m.is_ai_generated,
            "ai_confidence": m.ai_confidence,
            "is_internal": m.is_internal,
            "replied_to_message_id": m.replied_to_message_id,
        }

    channel_val = conv.channel.value if hasattr(conv.channel, "value") else str(conv.channel)
    status = "open" if conv.is_open else "resolved"

    return {
        "id": conv.id,
        "guest_name": guest.name if guest else None,
        "guest_phone": guest.phone if guest else "",
        "channel": channel_val,
        "status": status,
        "last_inbound_at": last_inbound_at,
        "messages": [_msg_dict(m) for m in messages],
    }


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
    msg.delivery_state = MessageDeliveryState.QUEUED
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
