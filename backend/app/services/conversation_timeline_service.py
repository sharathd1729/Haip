"""
Merged conversation timeline (HAIP Inbox prototype-wiring plan, ticket 2):
messages + voice calls for one conversation's guest, one chronological feed.

NOT built on guest_events_service.get_guest_timeline()/get_inquiry_timeline():
checked first, and GuestEvent's message.sent/call.completed/call.analyzed
event types are defined in the taxonomy and used by the one-time
backfill_guest_events job, but are not emitted live from any message or call
ingestion path today (only message.received has a live call site, in
core/events.py's docstring example -- not actually invoked anywhere).
Reading the ledger here would silently show stale/incomplete calls and
outbound messages. Flagging that gap separately; this reads Message/Call
directly instead, same "computed on read" approach leads_service.py already
uses elsewhere.
"""
import json
from typing import Optional
from sqlalchemy.orm import Session

from app.models.conversation import Conversation, Message
from app.models.call import Call
from app.models.transcript import Transcript

TIMELINE_CAP = 50


def _normalise_turns(raw) -> list[dict]:
    """Same reshape calls.py::_serialize_call_detail already does for the
    Calls page -- reused here rather than duplicated. Transcript.turns is
    stored as a JSON string (Text column), not a native JSON column."""
    turns = json.loads(raw) if isinstance(raw, str) else (raw or [])
    out = []
    for t in turns:
        out.append({
            "speaker": t.get("speaker", "unknown"),
            "text": t.get("text", ""),
            "t0": t.get("t0", t.get("start", 0)),
            "t1": t.get("t1", t.get("end", 0)),
        })
    return out


def get_conversation_timeline(
    db: Session,
    tenant_id: str,
    conversation_id: str,
    limit: int = TIMELINE_CAP,
) -> Optional[dict]:
    """
    Returns {"items": [...], "capped": bool} or None if the conversation
    doesn't exist for this tenant. Each item is a discriminated union:
    {"type": "message", "occurred_at": ..., "message": {...}} or
    {"type": "call", "occurred_at": ..., "call": {...}}.
    """
    conv = db.query(Conversation).filter_by(id=conversation_id, tenant_id=tenant_id).first()
    if not conv:
        return None

    messages = (
        db.query(Message)
        .filter_by(conversation_id=conversation_id, tenant_id=tenant_id)
        .order_by(Message.created_at.desc())
        .limit(limit + 1)
        .all()
    )

    calls = (
        db.query(Call)
        .filter_by(guest_id=conv.guest_id, tenant_id=tenant_id)
        .order_by(Call.created_at.desc())
        .limit(limit + 1)
        .all()
    )
    call_ids = [c.id for c in calls]
    transcripts_by_call = {
        t.call_id: t
        for t in db.query(Transcript).filter(Transcript.call_id.in_(call_ids)).all()
    } if call_ids else {}

    # HAIP Inbox full-parity pass, ticket 6: reuse calls.py's own recording-
    # URL resolution (deferred import -- a service module importing an
    # endpoint module's helper at top-level would invert the normal
    # dependency direction).
    from app.api.v1.endpoints.calls import _get_recording_url

    items = []
    for m in messages:
        items.append({
            "type": "message",
            "occurred_at": m.created_at,
            "message": {
                "id": m.id,
                "direction": m.direction.value if hasattr(m.direction, "value") else m.direction,
                "sender_name": m.sender_name,
                "body": m.body,
                "channel": m.channel.value if hasattr(m.channel, "value") else m.channel,
                "media_type": m.media_type,
                "media_url": m.media_url,
                "is_ai_generated": m.is_ai_generated,
                "was_approved": m.was_approved,
                "created_at": m.created_at,
                "suggested_actions": m.suggested_actions or [],
            },
        })

    for c in calls:
        transcript = transcripts_by_call.get(c.id)
        items.append({
            "type": "call",
            "occurred_at": c.created_at,
            "call": {
                "id": c.id,
                "direction": c.direction.value if hasattr(c.direction, "value") else c.direction,
                "duration_seconds": c.duration_seconds or 0,
                "started_at": c.started_at,
                # HAIP Inbox full-parity pass, ticket 6: same presigned/local
                # URL resolution calls.py's own /calls/{id} detail endpoint
                # already uses -- reused here rather than exposing the raw
                # recording_s3_key (an internal storage path) to the
                # frontend directly.
                "recording_url": _get_recording_url(c.recording_s3_key, call_id=c.id),
                "ai_summary": c.ai_summary,
                "conversion_probability": c.conversion_probability,
                "turns": _normalise_turns(transcript.turns if transcript else None),
            },
        })

    items.sort(key=lambda it: it["occurred_at"], reverse=True)
    capped = len(items) > limit
    items = items[:limit]
    items.reverse()  # oldest first, matching the prototype's chat-thread order

    return {"items": items, "capped": capped}
