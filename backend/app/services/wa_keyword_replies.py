"""WhatsApp keyword auto-replies: an automation_rules row with trigger ``wa_message_received`` and action
``send_whatsapp_reply`` answers a guest's message before the AI concierge. The guest just wrote, so WhatsApp's 24-hour
window is open.

Trigger (``WaReplyTrigger``): keywords matched as whole words (``match="word"``, any case) or as the whole message
(``match="exact"``: "Hi!" matches "hi", "hi, rates?" does not); exclude words; ``reply_all``; ``hours`` = any | open |
closed against the team hours in Settings (agent_consult_settings). A rule whose keyword matched wins over a reply-all
rule, then the oldest rule first.

Reply (``WaReplyAction``): text, up to 3 reply buttons or a link button (services/wa_interactive.py), and up to 5
files (PDF or JPEG/PNG photo uploaded via ``POST /automations/wa-reply-file``). One file is sent with the text as one
message (its caption, or the header of the buttons / link message); several go as the text first, then each file as its
own message in order (a Celery chain, so they arrive in that order). Rules saved with the old single ``file`` are read
as a one-item ``files`` list. ``once_per_person`` or ``repeat_after_hours``.

A reply that only fires when closed is an away message: it is sent with sender_kind ``automation_away``, which never
counts as an answer (the guest stays on Needs reply / My day for the team) or as a person's contact.

Keyword matching is shared with Instagram (ig_keyword_match). Opt-out words are handled earlier in the inbound task,
so a STOP never reaches here.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import structlog
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.models.automation import AutomationRule, AutomationRun

log = structlog.get_logger()

TRIGGER = "wa_message_received"
ACTION = "send_whatsapp_reply"
KIND = "automation"
AWAY_KIND = "automation_away"  # also listed in inbox_service, work_queue_signals and ai_draft_expiry
FILE_FOLDER = "wa_replies"
MAX_FILES = 5


class WaReplyTrigger(BaseModel):
    keywords: list[str] = Field(default_factory=list, max_length=50)
    exclude_keywords: list[str] = Field(default_factory=list, max_length=50)
    reply_all: bool = False
    match: Literal["word", "exact"] = "word"
    hours: Literal["any", "open", "closed"] = "any"

    @model_validator(mode="after")
    def _something(self):
        self.keywords = [k.strip() for k in self.keywords if k and k.strip()]
        if not self.reply_all and not self.keywords:
            raise ValueError("Add at least one keyword.")
        return self


class WaLink(BaseModel):
    title: str = Field(min_length=1, max_length=20)
    url: str = Field(min_length=9, max_length=2000)


class WaFile(BaseModel):
    key: str = Field(min_length=10, max_length=300)
    kind: Literal["document", "image"]
    filename: str = Field(default="", max_length=120)


class WaReplyAction(BaseModel):
    message: str = Field(min_length=1, max_length=1024)
    buttons: list[str] = Field(default_factory=list, max_length=3)
    link: WaLink | None = None
    files: list[WaFile] = Field(default_factory=list, max_length=MAX_FILES)
    once_per_person: bool = False
    repeat_after_hours: int | None = Field(default=None, ge=1, le=168)

    @model_validator(mode="before")
    @classmethod
    def _drop_blanks(cls, data):
        if isinstance(data, dict):
            data = dict(data)
            data["buttons"] = [str(b).strip() for b in (data.get("buttons") or []) if str(b or "").strip()]
            link = data.get("link") or {}
            if not str(link.get("url") or "").strip() and not str(link.get("title") or "").strip():
                data["link"] = None
            old = data.pop("file", None)  # rules saved before several files: one optional ``file``
            files = data.get("files") if data.get("files") is not None else ([old] if old else [])
            data["files"] = [f for f in files if isinstance(f, dict) and f.get("key")]
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


def validate_rule(trigger_config: dict, action_config: dict, tenant_id: str | None = None) -> tuple[dict, dict]:
    """Validated copies of both configs. Raises pydantic.ValidationError / ValueError. A file must be one this
    workspace uploaded (its storage key starts with ``{tenant_id}/wa_replies/``)."""
    action = WaReplyAction(**(action_config or {}))
    if any(not tenant_id or not f.key.startswith(f"{tenant_id}/{FILE_FOLDER}/") for f in action.files):
        raise ValueError("Upload the file again: it does not belong to this workspace.")
    return WaReplyTrigger(**(trigger_config or {})).model_dump(), action.model_dump(exclude_none=True)


def _norm(text: str) -> str:
    """Lower case, punctuation and emoji dropped, single spaces: "Hi!! 👋" -> "hi"."""
    return " ".join(re.sub(r"[^\w\s]|_", " ", (text or "").lower()).split())


def _matches(text: str, tc: dict) -> bool:
    from app.services.ig_keyword_match import _contains_keyword, _keyword_list

    words = _keyword_list(tc.get("keywords"))
    if tc.get("match") == "exact":
        return _norm(text) in {_norm(k) for k in words}
    return _contains_keyword(text, words)


def find_rule(db: Session, tenant_id: str, text: str) -> AutomationRule | None:
    from app.services.ig_keyword_match import _contains_keyword, _keyword_list

    rules = (
        db.query(AutomationRule)
        .filter_by(tenant_id=tenant_id, trigger=TRIGGER, action=ACTION, is_active=True)
        .order_by(AutomationRule.created_at)
        .all()
    )
    open_now: bool | None = None
    catch_all = None
    for rule in rules:
        tc = rule.trigger_config or {}
        hours = tc.get("hours") or "any"
        if hours != "any":
            if open_now is None:
                from app.models.tenant import Tenant
                from app.services import agent_consult_settings

                open_now = agent_consult_settings.in_business_hours(db.get(Tenant, tenant_id))
            if open_now != (hours == "open"):
                continue
        if _contains_keyword(text, _keyword_list(tc.get("exclude_keywords"))):
            continue
        if _matches(text, tc):
            return rule
        if tc.get("reply_all") and catch_all is None:
            catch_all = rule
    return catch_all


def _last_reply_at(db: Session, tenant_id: str, conversation_id: str, rule_id: str) -> datetime | None:
    from app.models.conversation import Message, MessageDirection

    rows = (
        db.query(Message.channel_metadata, Message.created_at)
        .filter(Message.tenant_id == tenant_id, Message.conversation_id == conversation_id,
                Message.direction == MessageDirection.OUTBOUND, Message.sender_kind.in_((KIND, AWAY_KIND)))
        .all()
    )
    times = [at for m, at in rows if isinstance(m, dict) and m.get("automation_rule_id") == rule_id and at]
    return max(times) if times else None


def handle(db: Session, tenant_id: str, guest, conversation, text: str) -> bool:
    """Reply when a rule matches. True when it did (the AI should stay out). Commits."""
    rule = find_rule(db, tenant_id, text or "")
    if rule is None:
        return False
    cfg = rule.action_config or {}
    if cfg.get("once_per_person") or cfg.get("repeat_after_hours"):
        last = _last_reply_at(db, tenant_id, conversation.id, rule.id)
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            hours = cfg.get("repeat_after_hours")
            if cfg.get("once_per_person") or not hours or datetime.now(UTC) - last < timedelta(hours=int(hours)):
                return False  # already answered this person: let the AI or the team take it
    from app.models.conversation import Message, MessageDeliveryState

    try:
        action = WaReplyAction(**cfg)
        spec, files = action.interactive(), action.files
    except Exception:  # noqa: BLE001 -- a rule saved before validation existed: send it as plain text
        spec, files = None, []
    files = [f for f in files if f.key.startswith(f"{tenant_id}/{FILE_FOLDER}/")]  # never another workspace's file
    name = (getattr(guest, "name", "") or "").strip()
    first = name.split()[0] if name else "there"
    away = (rule.trigger_config or {}).get("hours") == "closed"
    body = (cfg.get("message") or "").replace("{first_name}", first)[:1024]
    lone = files[0] if len(files) == 1 else None  # one file rides with the text, as before several were allowed

    def _reply(text: str, file: WaFile | None, extra: dict) -> Message:
        meta = {"automation_rule_id": rule.id, **extra, **({"filename": file.filename} if file and file.filename else {})}
        return Message(
            id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conversation.id, direction="outbound",
            channel=conversation.channel, body=text, sender_kind=AWAY_KIND if away else KIND,
            sender_name=rule.name[:100] if rule.name else "Automation", channel_metadata=meta,
            delivery_state=MessageDeliveryState.PENDING,
            media_type=file.kind if file else None, media_url=file.key if file else None,
        )

    msg = _reply(body, lone, {"interactive": spec} if spec else {})
    # "part" marks the follow-up files, so stats count one reply per guest message, not one per file.
    parts = [_reply("", f, {"part": i}) for i, f in enumerate(files if lone is None else [], start=1)]
    db.add_all([msg, *parts])
    rule.run_count = (rule.run_count or 0) + 1
    rule.last_run_at = datetime.now(UTC)
    db.add(AutomationRun(id=str(uuid.uuid4()), tenant_id=tenant_id, automation_id=rule.id, automation_name=rule.name,
                         status="success", trigger_event=TRIGGER,
                         context={"conversation_id": conversation.id, "guest_id": getattr(guest, "id", None)},
                         detail=f"Replied: {msg.body[:100]}"))
    db.commit()
    _dispatch([msg.id, *(p.id for p in parts)], tenant_id)
    log.info("wa_keyword_reply_sent", tenant_id=tenant_id, rule_id=rule.id, files=len(files))
    return True


def _dispatch(message_ids: list[str], tenant_id: str) -> None:
    """Queue the reply's messages. Several go as one Celery chain so the guest gets them in order (send_whatsapp marks a
    final failure and returns, so one bad file does not hold back the rest; a retry holds them until it settles)."""
    from app.workers.tasks.send_whatsapp import send_whatsapp

    if len(message_ids) == 1:
        send_whatsapp.delay(message_id=message_ids[0], tenant_id=tenant_id)
        return
    from celery import chain

    chain(*(send_whatsapp.si(message_id=i, tenant_id=tenant_id) for i in message_ids)).apply_async()


def stats(db: Session, tenant_id: str, since: datetime) -> list[dict]:
    """Per rule since ``since``: replies that left HAIP (sent), reached the phone (delivered), were read, failed, and
    how many people got one. From the reply messages' own delivery state (Meta's status webhooks keep it current)."""
    from app.models.conversation import ChannelType, Message, MessageDirection
    from app.models.conversation import MessageDeliveryState as S

    rows = (
        db.query(Message.channel_metadata, Message.delivery_state, Message.conversation_id)
        .filter(Message.tenant_id == tenant_id, Message.direction == MessageDirection.OUTBOUND,
                Message.channel == ChannelType.WHATSAPP, Message.sender_kind.in_((KIND, AWAY_KIND)),
                Message.created_at >= since)
        .all()
    )
    out: dict[str, dict] = {}
    people: dict[str, set] = {}
    for meta, state, conv_id in rows:
        rule_id = meta.get("automation_rule_id") if isinstance(meta, dict) else None
        if not rule_id or meta.get("part"):
            continue
        s = out.setdefault(rule_id, {"rule_id": rule_id, "sent": 0, "delivered": 0, "read": 0, "failed": 0, "people": 0})
        if state in (S.SENT, S.DELIVERED, S.READ):
            s["sent"] += 1
        if state in (S.DELIVERED, S.READ):
            s["delivered"] += 1
        if state == S.READ:
            s["read"] += 1
        if state in (S.FAILED, S.REJECTED):
            s["failed"] += 1
        people.setdefault(rule_id, set()).add(conv_id)
    for rule_id, s in out.items():
        s["people"] = len(people[rule_id])
    return list(out.values())
