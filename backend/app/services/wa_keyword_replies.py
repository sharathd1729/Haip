"""WhatsApp keyword auto-replies: an automation_rules row with trigger ``wa_message_received`` and action
``send_whatsapp_reply`` answers a guest's message that contains one of its keywords (whole words, any case), before
the AI concierge. The reply is text, up to 3 reply buttons or a link button (services/wa_interactive.py). The guest
just wrote, so WhatsApp's 24-hour window is open.

Keyword matching is shared with Instagram (ig_keyword_match). Opt-out words are handled earlier in the inbound task,
so a STOP never reaches here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.models.automation import AutomationRule, AutomationRun

log = structlog.get_logger()

TRIGGER = "wa_message_received"
ACTION = "send_whatsapp_reply"


class WaReplyTrigger(BaseModel):
    keywords: list[str] = Field(default_factory=list, max_length=50)
    exclude_keywords: list[str] = Field(default_factory=list, max_length=50)
    reply_all: bool = False

    @model_validator(mode="after")
    def _something(self):
        self.keywords = [k.strip() for k in self.keywords if k and k.strip()]
        if not self.reply_all and not self.keywords:
            raise ValueError("Add at least one keyword.")
        return self


class WaLink(BaseModel):
    title: str = Field(min_length=1, max_length=20)
    url: str = Field(min_length=9, max_length=2000)


class WaReplyAction(BaseModel):
    message: str = Field(min_length=1, max_length=1024)
    buttons: list[str] = Field(default_factory=list, max_length=3)
    link: WaLink | None = None
    once_per_person: bool = False

    @model_validator(mode="before")
    @classmethod
    def _drop_blanks(cls, data):
        if isinstance(data, dict):
            data = dict(data)
            data["buttons"] = [str(b).strip() for b in (data.get("buttons") or []) if str(b or "").strip()]
            link = data.get("link") or {}
            if not str(link.get("url") or "").strip() and not str(link.get("title") or "").strip():
                data["link"] = None
        return data

    @model_validator(mode="after")
    def _one_kind(self):
        if self.buttons and self.link:
            raise ValueError("Use either reply buttons or a link button, not both.")
        spec = self.interactive()
        if spec:
            from app.services import wa_interactive

            wa_interactive.validate(spec)  # raises with Meta's limits (20 characters, https, …)
        return self

    def interactive(self) -> dict | None:
        if self.link:
            return {"kind": "cta_url", "title": self.link.title, "url": self.link.url}
        if self.buttons:
            return {"kind": "buttons", "buttons": self.buttons}
        return None


def validate_rule(trigger_config: dict, action_config: dict) -> tuple[dict, dict]:
    """Validated copies of both configs. Raises pydantic.ValidationError / ValueError."""
    return WaReplyTrigger(**(trigger_config or {})).model_dump(), WaReplyAction(**(action_config or {})).model_dump(exclude_none=True)


def find_rule(db: Session, tenant_id: str, text: str) -> AutomationRule | None:
    from app.services.ig_keyword_match import _contains_keyword, _keyword_list

    rules = (
        db.query(AutomationRule)
        .filter_by(tenant_id=tenant_id, trigger=TRIGGER, action=ACTION, is_active=True)
        .order_by(AutomationRule.created_at)
        .all()
    )
    for rule in rules:
        tc = rule.trigger_config or {}
        if _contains_keyword(text, _keyword_list(tc.get("exclude_keywords"))):
            continue
        if tc.get("reply_all") or _contains_keyword(text, _keyword_list(tc.get("keywords"))):
            return rule
    return None


def _already_replied(db: Session, tenant_id: str, conversation_id: str, rule_id: str) -> bool:
    from app.models.conversation import Message, MessageDirection

    rows = (
        db.query(Message.channel_metadata)
        .filter(Message.tenant_id == tenant_id, Message.conversation_id == conversation_id,
                Message.direction == MessageDirection.OUTBOUND, Message.sender_kind == "automation")
        .all()
    )
    return any(isinstance(m, dict) and m.get("automation_rule_id") == rule_id for (m,) in rows)


def handle(db: Session, tenant_id: str, guest, conversation, text: str) -> bool:
    """Reply when a rule matches. True when it did (the AI should stay out). Commits."""
    rule = find_rule(db, tenant_id, text or "")
    if rule is None:
        return False
    cfg = rule.action_config or {}
    if cfg.get("once_per_person") and _already_replied(db, tenant_id, conversation.id, rule.id):
        return False  # already answered this person once: let the AI or the team take it
    from app.models.conversation import Message, MessageDeliveryState

    try:
        spec = WaReplyAction(**cfg).interactive()
    except Exception:  # noqa: BLE001 -- a rule saved before validation existed: send it as plain text
        spec = None
    name = (getattr(guest, "name", "") or "").strip()
    first = name.split()[0] if name else "there"
    meta = {"automation_rule_id": rule.id, **({"interactive": spec} if spec else {})}
    msg = Message(
        id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conversation.id, direction="outbound",
        channel=conversation.channel, body=(cfg.get("message") or "").replace("{first_name}", first)[:1024],
        sender_kind="automation", sender_name=rule.name[:100] if rule.name else "Automation",
        channel_metadata=meta, delivery_state=MessageDeliveryState.PENDING,
    )
    db.add(msg)
    rule.run_count = (rule.run_count or 0) + 1
    rule.last_run_at = datetime.now(UTC)
    db.add(AutomationRun(id=str(uuid.uuid4()), tenant_id=tenant_id, automation_id=rule.id, automation_name=rule.name,
                         status="success", trigger_event=TRIGGER,
                         context={"conversation_id": conversation.id, "guest_id": getattr(guest, "id", None)},
                         detail=f"Replied: {msg.body[:100]}"))
    db.commit()
    from app.workers.tasks.send_whatsapp import send_whatsapp

    send_whatsapp.delay(message_id=msg.id, tenant_id=tenant_id)
    log.info("wa_keyword_reply_sent", tenant_id=tenant_id, rule_id=rule.id)
    return True
