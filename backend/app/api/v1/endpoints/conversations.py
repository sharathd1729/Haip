import uuid
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.api.v1.deps import get_current_user
from app.models.user import User
from app.models.conversation import Conversation, Message, MessageDeliveryState
from app.schemas.conversation import MessageOut, SendMessageRequest, AIDraftRequest, ConversationOut, SendTemplateRequest, ApproveDraftRequest, RewriteDraftRequest
from app.workers.tasks.concierge_draft import concierge_draft
from app.services import ai_draft_outcomes_service
import structlog

log = structlog.get_logger()
router = APIRouter(prefix="/conversations", tags=["conversations"])

# Maximum length for Idempotency-Key header values
_IDEMPOTENCY_KEY_MAX_LEN = 64
# Deduplication window
_IDEMPOTENCY_WINDOW_HOURS = 24


def _validate_iso_cursor(value: str, param_name: str) -> None:
    """Validate a `before` pagination cursor is a real ISO timestamp. 422s on
    a malformed cursor rather than silently returning an unfiltered (or
    empty) page. Validation only -- callers compare the raw string, not a
    parsed datetime, wherever the target column is itself string-typed
    (Conversation.last_message_at) rather than DateTime."""
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid `{param_name}` timestamp")


def _parse_cursor(value: str, param_name: str) -> datetime:
    """Same validation as _validate_iso_cursor, returning the parsed
    datetime -- for comparing against genuine DateTime columns
    (Message.created_at), unlike Conversation.last_message_at which is
    string-typed and must be compared as a string (see that column's
    definition)."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid `{param_name}` timestamp")


@router.get("", response_model=List[ConversationOut])
def list_conversations(
    channel: str = None,
    is_open: bool = None,
    sort: str = Query(default="smart", pattern="^(smart|recent|unread)$"),
    limit: int = Query(default=50, le=200),
    before: str | None = Query(None, description="ISO timestamp cursor (last_message_at) -- return conversations older than this, for 'load more'"),
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
    if before:
        # last_message_at is a String column (not DateTime) -- compare the
        # raw ISO string. Same-format ISO-8601 sorts lexicographically
        # identically to chronological order, same reasoning leads_service
        # already relies on for its string-typed date filters.
        _validate_iso_cursor(before, "before")
        q = q.filter(Conversation.last_message_at < before)

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

    conversations = q.limit(limit).all()
    if not conversations:
        return []

    # Batch-fetch the latest message per conversation in one query (avoids N+1).
    conv_ids = [c.id for c in conversations]
    latest_rows = (
        db.query(Message.conversation_id, Message.body)
        .filter(Message.conversation_id.in_(conv_ids), Message.tenant_id == current_user.tenant_id)
        .order_by(Message.conversation_id, Message.created_at.desc())
        .distinct(Message.conversation_id)
        .all()
    )
    preview_by_conv = {row.conversation_id: row.body for row in latest_rows}

    # T0.5: batch-fetch ad_title from each conversation's earliest message
    # carrying ad-attribution metadata (Meta only sets referral on the
    # message that actually originated from the ad).
    ad_rows = (
        db.query(Message.conversation_id, Message.channel_metadata)
        .filter(
            Message.conversation_id.in_(conv_ids),
            Message.tenant_id == current_user.tenant_id,
            Message.channel_metadata.isnot(None),
        )
        .order_by(Message.conversation_id, Message.created_at.asc())
        .distinct(Message.conversation_id)
        .all()
    )
    ad_title_by_conv = {}
    for row in ad_rows:
        referral = (row.channel_metadata or {}).get("referral") or {}
        ad_title = (referral.get("ads_context_data") or {}).get("ad_title")
        if ad_title:
            ad_title_by_conv[row.conversation_id] = ad_title

    result = []
    for c in conversations:
        out = ConversationOut.model_validate(c)
        out.guest_name = c.guest.name if c.guest else None
        out.last_message = preview_by_conv.get(c.id)
        out.ad_title = ad_title_by_conv.get(c.id)
        result.append(out)
    return result


def _iso(val) -> "str | None":
    if val is None:
        return None
    if isinstance(val, str):
        return val
    return val.isoformat()


def _resolve_media_url(m: Message) -> "str | None":
    """WhatsApp media (T1.2) is stored as an object-storage key, not a
    URL -- Meta's own download links are short-lived and can't be
    persisted directly. Presign on read. Instagram's media_url is
    already a direct (long-lived) Meta CDN link, stored as-is -- pass
    through unchanged."""
    if not m.media_url:
        return None
    if m.media_url.startswith("http://") or m.media_url.startswith("https://"):
        return m.media_url
    from app.services.media_storage import get_presigned_media_url
    return get_presigned_media_url(m.media_url)


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
        "media_url": _resolve_media_url(m),   # T0.5 / T1.2
        "media_type": m.media_type,
        "shared_post_url": (m.channel_metadata or {}).get("shared_post_url"),
        "suggested_actions": m.suggested_actions or [],
    }


@router.get("/{conversation_id}/messages")
def get_messages(
    conversation_id: str,
    before: str | None = Query(None, description="ISO timestamp cursor -- return messages older than this, for 'load older'"),
    limit: int = Query(default=50, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cursor-paginated "load older messages". get_conversation_detail's
    initial payload only carries the most recent `limit` messages -- this is
    how the thread reaches further back in history on scroll-up.

    Returns {messages, has_more} rather than a bare list (unlike
    list_conversations) since this endpoint was previously unused by the
    frontend -- no existing bare-array contract to preserve."""
    conv = db.query(Conversation).filter_by(id=conversation_id, tenant_id=current_user.tenant_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    q = db.query(Message).filter_by(conversation_id=conversation_id, tenant_id=current_user.tenant_id)
    if before:
        q = q.filter(Message.created_at < _parse_cursor(before, "before"))

    messages = q.order_by(Message.created_at.desc()).limit(limit).all()
    messages.reverse()  # chronological order for display

    return {
        "messages": [_msg_dict(m) for m in messages],
        "has_more": len(messages) == limit,
    }


@router.get("/{conversation_id}/timeline")
def get_conversation_timeline_endpoint(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """HAIP Inbox prototype-wiring plan, ticket 2: messages + calls for this
    conversation's guest, merged into one chronological feed -- the data
    behind the inbox thread's Sarvam call-log cards alongside chat bubbles."""
    from app.services.conversation_timeline_service import get_conversation_timeline

    result = get_conversation_timeline(db, tenant_id=current_user.tenant_id, conversation_id=conversation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return result


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


@router.post("/{conversation_id}/send-template", response_model=MessageOut, status_code=201)
def send_template_message(
    conversation_id: str,
    body: SendTemplateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    T3.2: send an approved template to re-open a closed WhatsApp service
    window (previously a dead toast stub in the inbox UI -- clicking
    "Send template" did nothing). Only meaningful for WhatsApp; other
    channels don't have Meta's 24h-window/template requirement.
    """
    from app.api.v1.endpoints.messaging import WATemplate, TemplateStatus
    from app.models.conversation import ChannelType

    conv = db.query(Conversation).filter_by(id=conversation_id, tenant_id=current_user.tenant_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    channel = str(conv.channel.value if hasattr(conv.channel, "value") else conv.channel)
    if channel != "whatsapp":
        raise HTTPException(status_code=422, detail="Templates can only be sent on WhatsApp conversations")

    tmpl = db.query(WATemplate).filter_by(id=body.template_id, tenant_id=current_user.tenant_id).first()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    if tmpl.status != TemplateStatus.APPROVED:
        raise HTTPException(status_code=422, detail="Only approved templates can be sent")

    # Render the template body text (for display in the thread) by
    # substituting {{1}}, {{2}}, ... with the supplied variables.
    body_component = next((c for c in (tmpl.components or []) if c.get("type") == "BODY"), None)
    display_text = body_component.get("text", "") if body_component else tmpl.name
    for i, var in enumerate(body.variables or [], start=1):
        display_text = display_text.replace(f"{{{{{i}}}}}", str(var))

    msg = Message(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        conversation_id=conversation_id,
        direction="outbound",
        channel=conv.channel,
        body=display_text,
        sender_id=current_user.id,
        sender_name=current_user.name,
        was_approved=True,
        delivery_state=MessageDeliveryState.QUEUED,
        channel_status="queued",
        channel_metadata={"template_id": tmpl.id, "template_name": tmpl.name},
    )
    db.add(msg)
    conv.last_message_at = datetime.now(timezone.utc).isoformat()
    db.commit()
    db.refresh(msg)

    from app.workers.tasks.send_whatsapp import send_whatsapp_template
    send_whatsapp_template.delay(
        message_id=msg.id, tenant_id=current_user.tenant_id,
        template_name=tmpl.name, language_code=tmpl.language or "en_US",
        variables=body.variables or [],
    )

    log.info("send_template_message_queued", message_id=msg.id, conversation_id=conversation_id, template=tmpl.name)
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
        tone=body.tone,
    )
    return {"status": "draft_queued", "draft_id": draft_id}


@router.post("/{conversation_id}/messages/{message_id}/rewrite")
def rewrite_draft_endpoint(
    conversation_id: str,
    message_id: str,
    body: RewriteDraftRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """HAIP Inbox prototype-wiring plan, ticket 3: real translate/tone-fix.
    Queues rewrite_draft, which updates the same Message.body in place --
    frontend refetches the conversation the same way it already does for
    ai-draft, rather than tracking a second draft id."""
    from app.workers.tasks.rewrite_draft import rewrite_draft

    msg = db.query(Message).filter_by(
        id=message_id, conversation_id=conversation_id, tenant_id=current_user.tenant_id
    ).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if not msg.is_ai_generated or msg.was_approved is not None:
        raise HTTPException(status_code=409, detail="Only a pending AI draft can be rewritten")

    rewrite_draft.delay(
        message_id=message_id,
        tenant_id=current_user.tenant_id,
        tone=body.tone,
        target_language=body.target_language,
    )
    return {"status": "rewrite_queued"}


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

    # Most recent messages first (chat UIs open at the bottom of history, not
    # the top) -- fetch newest N then reverse for chronological display.
    # Used to be .order_by(asc).limit(200), which for any thread with more
    # than 200 messages silently showed the OLDEST 200 instead of the most
    # recent ones -- the opposite of what every chat UI should default to.
    # Older history now reachable via GET /{id}/messages?before=... .
    _MESSAGES_INITIAL_LIMIT = 50
    total_messages = db.query(Message).filter_by(conversation_id=conversation_id).count()
    messages = (
        db.query(Message)
        .filter_by(conversation_id=conversation_id)
        .order_by(Message.created_at.desc())
        .limit(_MESSAGES_INITIAL_LIMIT)
        .all()
    )
    messages.reverse()

    # D9: compute last_inbound_at — most recent inbound message timestamp
    last_inbound: "Message | None" = (
        db.query(Message)
        .filter_by(conversation_id=conversation_id, direction="inbound")
        .order_by(Message.created_at.desc())
        .first()
    )
    last_inbound_at = _iso(last_inbound.created_at) if last_inbound else None

    channel_val = conv.channel.value if hasattr(conv.channel, "value") else str(conv.channel)
    status = "open" if conv.is_open else "resolved"

    # HAIP Inbox prototype-wiring plan, ticket 5: the frontend needs
    # guest_id/inquiry_id for the profile-completeness widget, follow-up
    # tasks, and the "add phone signal" action -- none of these were
    # exposed here before (only guest_name/guest_phone, no ids at all).
    inquiry_id = None
    if conv.inquiry_id:
        inquiry_id = conv.inquiry_id
    else:
        from app.models.inquiry import Inquiry
        latest_inquiry = (
            db.query(Inquiry.id)
            .filter_by(guest_id=conv.guest_id, tenant_id=current_user.tenant_id)
            .order_by(Inquiry.created_at.desc())
            .first()
        )
        inquiry_id = latest_inquiry.id if latest_inquiry else None

    return {
        "id": conv.id,
        "guest_id": conv.guest_id,
        "inquiry_id": inquiry_id,
        "guest_name": guest.name if guest else None,
        "guest_phone": guest.phone if guest else "",
        "channel": channel_val,
        "status": status,
        "last_inbound_at": last_inbound_at,
        "messages": [_msg_dict(m) for m in messages],
        "total_messages": total_messages,
        "messages_capped": total_messages > len(messages),
    }


@router.post("/{conversation_id}/messages/{message_id}/approve")
def approve_ai_draft(
    conversation_id: str,
    message_id: str,
    body: ApproveDraftRequest = ApproveDraftRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    msg = db.query(Message).filter_by(
        id=message_id, conversation_id=conversation_id, tenant_id=current_user.tenant_id
    ).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    # AI Autonomy Plan §0.1: this used to ignore any edited text entirely --
    # the inbox UI's edit-then-send flow already posted {text: editText}
    # here, but with no body param declared FastAPI silently dropped it and
    # the ORIGINAL AI draft always went out to the guest, edit or not.
    original_body = msg.body
    was_edited = body.text is not None and body.text != original_body
    if body.text is not None:
        msg.body = body.text

    msg.was_approved = True
    msg.sender_id = current_user.id
    msg.delivery_state = MessageDeliveryState.QUEUED

    ai_draft_outcomes_service.record_outcome(
        db, tenant_id=current_user.tenant_id, draft=msg,
        outcome="sent_edited" if was_edited else "sent_verbatim",
        original_body=original_body if was_edited else None,
        sent_body=msg.body if was_edited else None,
    )
    db.commit()

    from app.workers.tasks.send_whatsapp import send_whatsapp
    send_whatsapp.delay(message_id=message_id, tenant_id=current_user.tenant_id)
    return {"status": "approved_and_queued"}


@router.post("/{conversation_id}/messages/{message_id}/reject")
def reject_ai_draft(
    conversation_id: str,
    message_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Was previously missing entirely -- the inbox UI's reject button has
    called this exact path since it was built, always 404ing silently
    (caught and swallowed client-side), so a rejected draft never actually
    got was_approved=False and never left any record of the rejection."""
    msg = db.query(Message).filter_by(
        id=message_id, conversation_id=conversation_id, tenant_id=current_user.tenant_id
    ).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    msg.was_approved = False
    msg.delivery_state = None

    ai_draft_outcomes_service.record_outcome(
        db, tenant_id=current_user.tenant_id, draft=msg, outcome="rejected",
    )
    db.commit()

    return {"status": "rejected"}


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
