"""
AI Concierge service — drafts WhatsApp replies using brand-voice + KB RAG.
"""
from sqlalchemy.orm import Session
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

    # KB retrieval, keyed on the message actually being replied to.
    #
    # This section was dead from migration 001 until 2026-08-20: pgvector, the
    # `embeddings` table and a `_kb_search()` helper all existed, but nothing
    # ever wrote a vector and nothing ever called the helper -- `kb_snippets`
    # was hardcoded to [] here, so every draft rendered an empty "KNOWLEDGE
    # BASE" heading to the model. Grounding (calculator_service) covers live
    # availability and price; this covers everything else the guest asks
    # about -- amenities, add-ons, routes, locations, policies.
    kb_snippets: list = []
    inbound = db.query(Message).filter_by(id=message_id).first()
    query_text = (inbound.body if inbound else "") or ""
    if query_text.strip():
        try:
            from app.services import knowledge_service
            kb_snippets = knowledge_service.search_snippets(
                db,
                tenant_id,
                query_text,
                property_id=(conversation.property_id if conversation else None),
            )
        except Exception as exc:
            # Retrieval is an enhancement, never a dependency: a KB failure
            # degrades the draft to ungrounded rather than dropping the reply.
            log.warning("kb_snippets_failed", tenant_id=tenant_id, error=str(exc))
            kb_snippets = []

    return {
        "guest": guest,
        "tenant": tenant,
        "inquiry": inquiry,
        "recent_messages": recent_msgs,
        "call_summaries": call_summaries,
        "kb_snippets": kb_snippets,
    }
