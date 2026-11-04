"""Comment-to-DM for a published post (agency M3).

When an approved post carries `comment_dm` and goes live on Instagram, HAIP creates the matching keyword rule for that
post (automation_rules: trigger ig_comment_received, action send_instagram_quick_reply, scoped to the post's media id).
The existing Instagram comment pipeline (process_instagram_comment -> ig_keyword_match -> ig_quick_reply) then sends the
DM and the optional public reply. One rule per (content item, media id): a retried publish never makes two.
"""
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.automation import AutomationRule

TRIGGER, ACTION = "ig_comment_received", "send_instagram_quick_reply"


def activate(db: Session, tenant_id: str, item, payload: dict, media_id: Optional[str]) -> Optional[AutomationRule]:
    dm = payload.get("comment_dm") or {}
    if not dm.get("keyword") or not dm.get("message") or not media_id:
        return None
    for rule in db.query(AutomationRule).filter_by(tenant_id=tenant_id, trigger=TRIGGER, action=ACTION):
        cfg = rule.trigger_config or {}
        if cfg.get("media_id") == media_id and cfg.get("content_id") == item.id:
            return rule
    rule = AutomationRule(id=str(uuid.uuid4()), tenant_id=tenant_id,
                          name=f"Studio: {item.title} (comment {dm['keyword'].upper()})"[:255],
                          description="Made by Marketing Studio when the post was published.",
                          trigger=TRIGGER, action=ACTION, is_active=True,
                          trigger_config={"media_id": media_id, "keywords": [dm["keyword"]], "source": "marketing_studio",
                                          "content_id": item.id},
                          action_config={"message": dm["message"],
                                         **({"public_ack_pool": [dm["public_reply"]]} if dm.get("public_reply") else {})})
    db.add(rule)
    db.flush()
    append_audit(db, tenant_id=tenant_id, action="marketing.comment_dm.activated", actor_user_id="agency",
                 target_type="automation_rule", target_id=rule.id,
                 payload={"content_id": item.id, "media_id": media_id, "keyword": dm["keyword"]})
    return rule


def reply_all_rule(db: Session, tenant_id: str, media_id: str, message: str, public_reply: Optional[str], *,
                   actor_id: Optional[str], source: str = "chief") -> AutomationRule:
    """A post-wide rule (every comment on this media gets the DM, plus the optional public reply): the same pipeline as the
    Studio keyword rule (ig_keyword_match: post-scoped ``reply_all`` first). One per media; a repeat returns it."""
    for rule in db.query(AutomationRule).filter_by(tenant_id=tenant_id, trigger=TRIGGER, action=ACTION):
        cfg = rule.trigger_config or {}
        if cfg.get("media_id") == media_id and cfg.get("reply_all"):
            return rule
    rule = AutomationRule(id=str(uuid.uuid4()), tenant_id=tenant_id, name=f"AI Executive: reply to every comment ({media_id})"[:255],
                          description="Made by the AI Executive after the owner approved it.", trigger=TRIGGER, action=ACTION,
                          is_active=True, trigger_config={"media_id": media_id, "reply_all": True, "source": source},
                          action_config={"message": message, **({"public_ack_pool": [public_reply]} if public_reply else {})})
    db.add(rule)
    db.flush()
    append_audit(db, tenant_id=tenant_id, action="marketing.comment_dm.activated", actor_user_id=actor_id,
                 target_type="automation_rule", target_id=rule.id, payload={"media_id": media_id, "reply_all": True, "source": source})
    return rule
