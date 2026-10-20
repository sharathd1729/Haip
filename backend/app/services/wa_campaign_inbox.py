"""Show a campaign's template message in the guest's inbox thread.

Real case (Ratha, Sep 2026): a broadcast went out and guests received it, but
the message appeared nowhere in the inbox. A campaign send only wrote a
per-recipient report row, so an agent opening the chat saw no sign of what the
guest was replying to.

The message is stored like any other outbound WhatsApp message (same thread,
same wamid), so delivery ticks, the guest's reply and the AI's context all
line up with it.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy.orm import Session

log = structlog.get_logger()

_VAR = re.compile(r"\{\{\s*(\d+)\s*\}\}")


def render_text(template_components: list, sent_components: list) -> str:
    """What the guest read: the template's text with the values actually sent
    filled into {{1}}, {{2}}..., header text first and footer last."""
    values: dict[str, list[str]] = {}
    for comp in sent_components or []:
        ctype = (comp.get("type") or "").lower()
        values[ctype] = [str(p.get("text", "")) for p in comp.get("parameters") or [] if p.get("type") == "text"]

    def fill(text: str, kind: str) -> str:
        vals = values.get(kind, [])
        return _VAR.sub(lambda m: vals[int(m.group(1)) - 1] if 0 < int(m.group(1)) <= len(vals) else "", text or "")

    parts: list[str] = []
    for comp in template_components or []:
        ctype = (comp.get("type") or "").upper()
        if ctype == "HEADER" and (comp.get("format") or "TEXT").upper() == "TEXT" and comp.get("text"):
            parts.append(fill(comp["text"], "header"))
        elif ctype == "BODY" and comp.get("text"):
            parts.append(fill(comp["text"], "body"))
        elif ctype == "FOOTER" and comp.get("text"):
            parts.append(comp["text"])
    return "\n\n".join(p for p in parts if p).strip()


def _guest_id(db: Session, tenant_id: str, recipient: Any) -> Optional[str]:
    """The recipient's guest: the CRM lead itself, or the guest found (or
    created) for a subscriber's phone through the one identity service."""
    gid = getattr(recipient, "guest_id", None)
    if gid:
        return gid
    from app.services.identity_service import resolve_gid
    gid, _ = resolve_gid(
        db=db, tenant_id=tenant_id, signal_type="phone", value=recipient.phone, source="campaign",
        guest_fields={"name": getattr(recipient, "name", None) or "Unknown", "phone": recipient.phone},
    )
    return gid


_STATE = {"sent": "SENT", "delivered": "DELIVERED", "read": "READ"}


def _store(db: Session, tenant_id: str, campaign: Any, template: Any, recipient: Any,
           body: str, wamid: str, status: str, when: Optional[datetime]) -> Optional[str]:
    """Write one campaign message into the guest's WhatsApp thread (find or
    create it). The caller owns the commit/rollback."""
    from app.models.conversation import (
        ChannelType, Conversation, Message, MessageDeliveryState, MessageDirection,
    )
    guest_id = _guest_id(db, tenant_id, recipient)
    if not guest_id:
        return None
    when = when or datetime.now(timezone.utc)
    conv = (
        db.query(Conversation)
        .filter_by(tenant_id=tenant_id, guest_id=guest_id, channel=ChannelType.WHATSAPP, is_open=True)
        .first()
    )
    if conv is None:
        from app.models.tenant import Tenant
        tenant = db.query(Tenant).filter_by(id=tenant_id).first()
        conv = Conversation(
            id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id,
            channel=ChannelType.WHATSAPP, is_open=True,
            ai_mode=(getattr(tenant, "wa_ai_mode_default", None) or "shadow"),
            # We wrote first, so nobody is "waiting on a reply" yet:
            # keeps the SLA clock off until the guest actually answers.
            first_response_at=when.isoformat(),
        )
        db.add(conv)
        db.flush()
    if not conv.last_message_at or conv.last_message_at < when.isoformat():
        conv.last_message_at = when.isoformat()
    msg = Message(
        id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conv.id,
        direction=MessageDirection.OUTBOUND, channel=ChannelType.WHATSAPP,
        body=body or f"Template: {template.name}",
        channel_message_id=wamid, channel_status=status,
        delivery_state=MessageDeliveryState[_STATE.get(status, "SENT")],
        channel_metadata={"kind": "campaign", "campaign_id": campaign.id, "template_id": template.id,
                          "template_name": template.name},
        sender_name=f"Campaign: {campaign.name}"[:255],
        sender_kind="campaign",                      # a broadcast is not a person contacting this guest
    )
    msg.created_at = when
    db.add(msg)
    return msg.id


def record_send(
    db: Session, tenant_id: str, campaign: Any, template: Any, recipient: Any,
    sent_components: list, response: Optional[dict],
) -> Optional[str]:
    """Add the sent template to the guest's WhatsApp thread. Returns the new
    message id, or None. Never raises: the message has already gone out, and
    a bookkeeping failure must not fail or retry the campaign."""
    try:
        wamid = ((response or {}).get("messages") or [{}])[0].get("id")
        if not wamid:
            return None
        # The recipient's "sent" state is already set; save it first so that
        # rolling back a failed inbox write below can never undo it.
        db.commit()
        mid = _store(db, tenant_id, campaign, template, recipient,
                     render_text(template.components, sent_components), wamid, "sent", None)
        db.commit()
        return mid
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.warning("campaign_inbox_record_failed", campaign_id=getattr(campaign, "id", None), error=str(exc))
        return None


def backfill(db: Session, tenant_id: str, campaign_id: Optional[str] = None) -> dict:
    """Add broadcasts sent before this existed to the inbox. Safe to run any
    number of times: a message Meta id already in the inbox is never added
    twice. Uses the report row's own send time and latest delivery status."""
    from app.api.v1.endpoints.messaging import WACampaign, WATemplate
    from app.models.conversation import Message
    from app.models.wa_campaign_recipient import WACampaignRecipient as Recipient
    from app.services import wa_template_service as wts

    q = db.query(Recipient).filter(
        Recipient.tenant_id == tenant_id, Recipient.wa_message_id.isnot(None),
        Recipient.status.in_(["sent", "delivered", "read"]),
    )
    if campaign_id:
        q = q.filter(Recipient.campaign_id == campaign_id)
    rows = q.order_by(Recipient.sent_at).all()
    have = {w for (w,) in db.query(Message.channel_message_id).filter(
        Message.tenant_id == tenant_id, Message.channel_message_id.in_([r.wa_message_id for r in rows] or [""])).all()}

    campaigns: dict = {}
    templates: dict = {}
    added = skipped = failed = 0
    for r in rows:
        if r.wa_message_id in have:
            skipped += 1
            continue
        camp = campaigns.get(r.campaign_id) or campaigns.setdefault(
            r.campaign_id, db.query(WACampaign).filter_by(id=r.campaign_id, tenant_id=tenant_id).first())
        tmpl = camp and (templates.get(camp.template_id) or templates.setdefault(
            camp.template_id, db.query(WATemplate).filter_by(id=camp.template_id, tenant_id=tenant_id).first()))
        if not camp or not tmpl:
            failed += 1
            continue
        try:
            try:
                body = render_text(tmpl.components, wts.build_send_components(tmpl.components, camp.variable_map or {}, r))
            except Exception:  # noqa: BLE001  -- header media etc.: fall back to the raw template text
                body = render_text(tmpl.components, [])
            if _store(db, tenant_id, camp, tmpl, r, body, r.wa_message_id, r.status, r.sent_at):
                added += 1
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            failed += 1
            log.warning("campaign_inbox_backfill_failed", wamid=r.wa_message_id, error=str(exc))
    log.info("campaign_inbox_backfilled", tenant_id=tenant_id, added=added, skipped=skipped, failed=failed)
    return {"added": added, "already_there": skipped, "failed": failed}
