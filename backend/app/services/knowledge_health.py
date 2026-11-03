"""Knowledge base health: every entry the bot cannot use and why, and what replies actually got from the knowledge base.

GET /knowledge/health (owner/manager, endpoints/knowledge_freshness.py). Reasons follow the retrieval rule in
knowledge_service._USABLE_SQL (active + approved + indexed + not out of date). "Used" comes from each AI draft's
channel_metadata["kb"] (concierge_service.kb_record, recorded since 4 Nov 2026). Read only: no LLM, no external call.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.conversation import Message
from app.models.knowledge import KnowledgeEntry
from app.services.knowledge_service import MAX_AUTO_ATTEMPTS

WORDS = {
    "waiting_approval": "Waiting for your approval",
    "indexing": "Being prepared for search",
    "failed": "Preparing for search failed; it will retry",
    "gave_up": "Preparing for search failed too often; press Re-index",
    "out_of_date": "No longer on the page or post it came from",
    "never_used": "Usable, but no reply used it in this period",
    "off": "Switched off",
    "rejected": "Rejected",
}
BLOCKING = ("waiting_approval", "indexing", "failed", "gave_up", "out_of_date")
MAX_DRAFTS = 5000  # newest AI drafts read for usage
MAX_LISTED = 200


def _reasons(e: KnowledgeEntry) -> list[str]:
    if not e.is_active:
        return ["off"]
    if e.review_status == "rejected":
        return ["rejected"]
    out = []
    if e.review_status != "approved":
        out.append("waiting_approval")
    if e.embedding_status == "pending":
        out.append("indexing")
    elif e.embedding_status == "failed":
        out.append("gave_up" if int(e.embedding_attempts or 0) >= MAX_AUTO_ATTEMPTS else "failed")
    if e.stale_since is not None:
        out.append("out_of_date")
    return out


def usage(db: Session, tenant_id: str, since: datetime) -> tuple[int, Counter, Counter]:
    """(drafts with a record, drafts per search status, times each entry was given to the AI) since `since`."""
    rows = (
        db.query(Message.channel_metadata)
        .filter(
            Message.tenant_id == tenant_id,
            Message.is_ai_generated.is_(True),
            Message.created_at >= since,
            Message.channel_metadata.isnot(None),
        )
        .order_by(Message.created_at.desc())
        .limit(MAX_DRAFTS)
        .all()
    )
    recorded, status, used = 0, Counter(), Counter()
    for (meta,) in rows:
        kb = (meta or {}).get("kb") if isinstance(meta, dict) else None
        if not isinstance(kb, dict):
            continue
        recorded += 1
        status[kb.get("status") or "unknown"] += 1
        used.update(h.get("id") for h in kb.get("hits") or [] if isinstance(h, dict) and h.get("id"))
    return recorded, status, used


def report(db: Session, tenant_id: str, days: int = 30) -> dict:
    since = datetime.now(UTC) - timedelta(days=days)
    recorded, status, used = usage(db, tenant_id, since)
    counts: Counter = Counter()
    listed = []
    usable = 0
    for e in (
        db.query(KnowledgeEntry)
        .filter(KnowledgeEntry.tenant_id == tenant_id)
        .order_by(KnowledgeEntry.updated_at.desc())
    ):
        reasons = _reasons(e)
        if not reasons:
            usable += 1
            if recorded and not used.get(e.id):
                reasons = ["never_used"]
        counts.update(reasons)
        if reasons and reasons[0] not in ("off", "rejected"):
            listed.append(
                {
                    "id": e.id,
                    "question": e.question,
                    "preview": (e.content or "")[:160],
                    "category": e.category,
                    "source": e.source,
                    "property_id": e.property_id,
                    "updated_at": e.updated_at.isoformat() if e.updated_at else None,
                    "reasons": [{"code": r, "words": WORDS[r]} for r in reasons],
                    "error": (e.embedding_error or "")[:200] if e.embedding_status == "failed" else None,
                    "times_used": used.get(e.id, 0),
                }
            )
    order = {code: i for i, code in enumerate(BLOCKING + ("never_used",))}
    listed.sort(key=lambda r: order[r["reasons"][0]["code"]])  # blocked first (stable: newest first within a reason)
    return {
        "period_days": days,
        "usable": usable,
        "blocked": sum(counts[r] for r in BLOCKING),
        "counts": {r: counts[r] for r in WORDS if counts[r]},
        "words": WORDS,
        "replies": {"recorded": recorded, "by_search_status": dict(status)},
        "entries": listed[:MAX_LISTED],
        "entries_capped": len(listed) > MAX_LISTED,
    }
