"""
AI Concierge service — drafts WhatsApp replies using brand-voice + KB RAG.
"""
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.conversation import Conversation, Message, MessageDirection
from app.models.tenant import Tenant
from app.models.call import Call
from app.models.transcript import Transcript
from app.core.cache import get_cached, set_cached
import structlog

log = structlog.get_logger()

# Debounce a burst of rapid inbound messages into one draft instead of one
# per message -- confirmed live: a guest sending "Hi" then "I want to book
# this weekend" a few seconds apart got two separate, disjointed AI
# replies. Not a context-window problem (build_concierge_context already
# pulls the last 20 conversation messages regardless of which one
# triggered the task) -- the bug is that two independent tasks each write
# their own draft Message row. Fixed delay from whichever message is
# currently "latest", not a sliding window that resets per message -- this
# codebase has never used Celery task revocation, and a fixed delay +
# staleness check at execution time gets the same practical outcome
# without needing it.
DEBOUNCE_SECONDS = 5


def _pending_draft_key(tenant_id: str, conversation_id: str) -> str:
    return f"haip:concierge_pending:{tenant_id}:{conversation_id}"


def mark_pending_draft(tenant_id: str, conversation_id: str, message_id: str) -> None:
    set_cached(_pending_draft_key(tenant_id, conversation_id), message_id, ttl=DEBOUNCE_SECONDS + 15)


def is_latest_pending_draft(tenant_id: str, conversation_id: str, message_id: str) -> bool:
    """False means a newer message arrived after this task was queued --
    that newer task (with its own fresh DEBOUNCE_SECONDS delay) is the one
    that should actually draft, this run should no-op. Redis-down/cache-
    miss fails open (True) -- losing the debounce optimization on a cache
    outage is fine, silently never drafting at all would not be."""
    return get_cached(_pending_draft_key(tenant_id, conversation_id)) in (message_id, None)


def unanswered_guest_text(db: Session, tenant_id: str, conversation_id: str) -> str:
    """All inbound message text since the conversation's last outbound
    message (or conversation start, if none) -- the guest's whole
    unanswered burst, not just whichever single message triggered this
    task. Used for grounding/KB-retrieval/escalation-checking so a burst
    like "Hi" + "I want to book this weekend" is treated as one combined
    query instead of just the last line -- matches what the LLM prompt
    already sees via recent_messages, which this doesn't feed into (that
    already spans the full history)."""
    last_outbound = (
        db.query(Message)
        .filter_by(conversation_id=conversation_id, direction=MessageDirection.OUTBOUND)
        .order_by(Message.created_at.desc())
        .first()
    )
    q = db.query(Message).filter(
        Message.conversation_id == conversation_id,
        Message.direction == MessageDirection.INBOUND,
    )
    if last_outbound:
        q = q.filter(Message.created_at > last_outbound.created_at)
    inbound = q.order_by(Message.created_at.asc()).all()

    lines = [m.body for m in inbound if m.body and not m.body.startswith("[")]
    return "\n".join(lines)


def _get_recent_messages(db: Session, conversation_id: str, limit: int = 20) -> list:
    """Confirmed live, a real self-reinforcing bug: an AI draft that was
    never approved/sent (still pending review, or rejected) was still being
    pulled into the NEXT completion's context as if it were part of the
    real conversation. One conversation accumulated 7 identical unsent
    "Thanks for your message! Let me check and get right back to you."
    drafts in its last 20 messages -- each guest follow-up then drafted
    against a prompt containing several copies of that same failed
    boilerplate line as "recent conversation," compounding the same
    failure pattern into a self-perpetuating loop. A draft the guest never
    actually saw isn't part of the conversation from their perspective, and
    feeding it back in is actively harmful, not neutral -- exclude any
    AI-generated message that wasn't actually sent (was_approved is True
    covers both human-approved-and-sent and autonomous sends)."""
    msgs = (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation_id,
            or_(Message.is_ai_generated.is_(False), Message.was_approved.is_(True)),
        )
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
) -> dict:
    """Assemble all context needed by the concierge_reply.jinja prompt.

    No longer takes message_id -- KB retrieval used to query on just the
    single triggering message's text; now uses unanswered_guest_text() so
    a burst of several rapid messages is treated as one combined query,
    matching the message-burst debounce fix (see DEBOUNCE_SECONDS above)."""
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
    query_text = unanswered_guest_text(db, tenant_id, conversation_id)
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
