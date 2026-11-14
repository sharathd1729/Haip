"""
T2.3 — send_instagram_quick_reply action: the entry the ingest tasks call for a keyword-matched Instagram DM, comment,
story reply or mention. The steps (public reply, private reply, follow gate, link button, events) live in
services/ig_automation.py; this wrapper keeps the call sites' signature.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.automation import AutomationRule


def dispatch_quick_reply(
    db: Session,
    tenant_id: str,
    rule: AutomationRule,
    recipient_id: str,
    guest_id: str,
    conversation_id: str,
    comment_id: Optional[str] = None,
    media_id: Optional[str] = None,
) -> bool:
    """Run the rule for this person. comment_id set = answer with a public reply + Meta's private reply (a plain DM to
    someone who only commented is refused). True when the DM went out."""
    from app.models.guest import Guest
    from app.services import ig_automation

    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first() if guest_id else None
    return ig_automation.start(db, tenant_id, rule, recipient_id=recipient_id, guest_id=guest_id,
                               conversation_id=conversation_id, comment_id=comment_id, media_id=media_id, guest=guest)
