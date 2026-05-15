import uuid
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.api.v1.deps import get_current_user
from app.models.user import User
from app.models.conversation import Conversation, Message
from app.schemas.conversation import MessageOut, SendMessageRequest, AIDraftRequest, ConversationOut
from app.workers.tasks.concierge_draft import concierge_draft
from datetime import datetime, timezone

router = APIRouter(prefix="/conversations", tags=["conversations"])


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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = db.query(Conversation).filter_by(id=conversation_id, tenant_id=current_user.tenant_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

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
    )
    db.add(msg)

    conv.last_message_at = datetime.now(timezone.utc).isoformat()
    db.commit()
    db.refresh(msg)

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

    # Create a placeholder message_id for the draft
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
