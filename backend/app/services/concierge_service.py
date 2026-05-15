"""
AI Concierge service — drafts WhatsApp replies using brand-voice + KB RAG.
"""
import json
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.conversation import Conversation, Message
from app.models.tenant import Tenant
from app.models.call import Call
from app.models.transcript import Transcript
import structlog

log = structlog.get_logger()


def _get_recent_messages(db: Session, conversation_id: str, limit: int = 20) -> list:
    msgs = (
        db.query(Message)
        .filter_by(conversation_id=conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {"direction": m.direction, "body": m.body or "", "at": m.created_at.isoformat() if m.created_at else ""}
        for m in reversed(msgs)
    ]


def _get_call_summaries(db: Session, tenant_id: str, guest_id: str, limit: int = 5) -> list:
    calls = (
        db.query(Call)
        .filter_by(tenant_id=tenant_id, guest_id=guest_id)
        .order_by(Call.created_at.desc())
        .limit(limit)
        .all()
    )
    return [{"summary": c.ai_summary, "duration": c.duration_seconds} for c in calls if c.ai_summary]


def _kb_search(db: Session, tenant_id: str, property_id: Optional[str], query_embedding: list, top_k: int = 5) -> list:
    """pgvector cosine similarity search over KB embeddings."""
    try:
        vec_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
        filter_clause = f"tenant_id = '{tenant_id}'"
        if property_id:
            filter_clause += f" AND (ref_id = '{property_id}' OR namespace = 'global')"

        rows = db.execute(text(f"""
            SELECT content, metadata,
                   1 - (embedding <=> '{vec_str}'::vector) AS score
            FROM embeddings
            WHERE {filter_clause}
            ORDER BY embedding <=> '{vec_str}'::vector
            LIMIT {top_k}
        """)).fetchall()
        return [{"text": r.content, "score": float(r.score), "source": json.loads(r.metadata or "{}").get("source", "kb")} for r in rows]
    except Exception as e:
        log.warning("kb_search_failed", error=str(e))
        return []


def build_concierge_context(
    db: Session,
    tenant_id: str,
    conversation_id: str,
    guest_id: str,
    message_id: str,
) -> dict:
    """Assemble all context needed by the concierge_reply.jinja prompt."""
    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    conversation = db.query(Conversation).filter_by(id=conversation_id).first()

    inquiry = None
    if conversation and conversation.inquiry_id:
        inquiry = db.query(Inquiry).filter_by(id=conversation.inquiry_id).first()

    recent_msgs = _get_recent_messages(db, conversation_id)
    call_summaries = _get_call_summaries(db, tenant_id, guest_id)

    return {
        "guest": guest,
        "tenant": tenant,
        "inquiry": inquiry,
        "recent_messages": recent_msgs,
        "call_summaries": call_summaries,
        "kb_snippets": [],  # populated by worker after embedding lookup
    }
