"""Packages in chat (WhatsApp step 3): send the workspace's published packages as a WhatsApp list, and answer a pick.

Reads ONLY sales_gateway.list_packages / get_package (published, guest-facing records; partner rates never shown) and
never puts a price in chat: prices go out through the team's quote (quote_service + Razorpay payment link), which
respects the tenant's price policy. A pick replies with the package's summary, inclusions and two buttons:
"Book this" (a callback task for the team, who send the quote and payment link) and "Talk to us".

Row ids: ``pkg:<key>``; button ids: ``pkgbook:<key>`` / ``pkgtalk:<key>``.
"""

from __future__ import annotations

import structlog
from sqlalchemy.orm import Session

log = structlog.get_logger()

PICK, BOOK, TALK = "pkg:", "pkgbook:", "pkgtalk:"


class CatalogError(ValueError):
    pass


def _cut(text: str | None, n: int) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def list_message(db: Session, tenant_id: str) -> tuple[str, dict]:
    """(body text, interactive list spec) for the published packages. Raises CatalogError when there are none."""
    from app.services import sales_gateway

    res = sales_gateway.list_packages(db, tenant_id, include_rates=False)
    pkgs = (res.data or [])[:10]
    if not pkgs:
        raise CatalogError("No packages are published yet. Publish them under Knowledge > Structured Business Data.")
    rows = []
    for p in pkgs:
        nights = f"{p['min_nights']}+ nights" if p.get("min_nights") else ""
        guests = f"up to {p['max_guests']} guests" if p.get("max_guests") else ""
        desc = _cut(p.get("summary") or " · ".join(x for x in (nights, guests) if x), 72)
        rows.append({"id": f"{PICK}{p['key']}"[:200], "title": _cut(p["name"], 24), **({"description": desc} if desc else {})})
    spec = {"kind": "list", "button": "See packages", "sections": [{"rows": rows}]}
    return "Here are our packages. Tap one to see what's included.", spec


def reply_id(msg: dict) -> str | None:
    i = msg.get("interactive") or {}
    return ((i.get("list_reply") or i.get("button_reply")) or {}).get("id")


def queue(db: Session, tenant_id: str, conversation, text: str, interactive: dict | None = None,
          *, sender_kind: str | None = "automation", sender_name: str = "Packages", source: str = "packages",
          sender_id: str | None = None) -> str:
    """Create the outbound WhatsApp message and queue its send (house pattern). Returns the message id."""
    import uuid

    from app.models.conversation import Message, MessageDeliveryState
    from app.workers.tasks.send_whatsapp import send_whatsapp

    msg = Message(id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=conversation.id, direction="outbound",
                  channel=conversation.channel, body=text[:1024], sender_kind=sender_kind, sender_name=sender_name[:100],
                  sender_id=sender_id, was_approved=sender_id is not None,
                  channel_metadata={"source": source, **({"interactive": interactive} if interactive else {})},
                  delivery_state=MessageDeliveryState.PENDING)
    db.add(msg)
    db.commit()
    send_whatsapp.delay(message_id=msg.id, tenant_id=tenant_id)
    return msg.id


def handle(db: Session, tenant_id: str, guest, conversation, msg: dict) -> bool:
    """A tap on a package row or its buttons: answer it. True when it was one."""
    rid = reply_id(msg) or ""
    if rid.startswith(PICK):
        return _on_pick(db, tenant_id, conversation, rid[len(PICK):])
    if rid.startswith(BOOK) or rid.startswith(TALK):
        key = rid.split(":", 1)[1]
        return _on_book(db, tenant_id, guest, conversation, key, wants_booking=rid.startswith(BOOK))
    return False


def _on_pick(db: Session, tenant_id: str, conversation, key: str) -> bool:
    from app.services import sales_gateway

    res = sales_gateway.get_package(db, tenant_id, key, include_rates=False)
    if not res.ok:
        queue(db, tenant_id, conversation, "That package isn't available right now. Our team will help you shortly.")
        return True
    p = res.data
    lines = [f"*{p['name']}*"]
    if p.get("summary"):
        lines.append(p["summary"])
    facts = []
    if p.get("min_nights"):
        facts.append(f"{p['min_nights']}{'-' + str(p['max_nights']) if p.get('max_nights') else '+'} nights")
    if p.get("max_guests"):
        facts.append(f"up to {p['max_guests']} guests")
    if facts:
        lines.append(" · ".join(facts))
    if p.get("inclusions"):
        lines.append("Included: " + ", ".join(p["inclusions"][:8]))
    text = _cut("\n".join(lines), 1000)
    spec = {"kind": "buttons", "buttons": ["Book this", "Talk to us"],
            "button_ids": [f"{BOOK}{key}"[:200], f"{TALK}{key}"[:200]]}
    queue(db, tenant_id, conversation, text, spec)
    return True


def _on_book(db: Session, tenant_id: str, guest, conversation, key: str, *, wants_booking: bool) -> bool:
    from app.models.task import Task
    from app.services import sales_gateway

    res = sales_gateway.get_package(db, tenant_id, key, include_rates=False)
    name = res.data["name"] if res.ok else key
    title = f"{'Send the quote and payment link' if wants_booking else 'Call back'}: {name}"
    try:
        db.add(Task(tenant_id=tenant_id, title=title[:255], guest_id=guest.id, priority="high", kind="call",
                    inquiry_id=getattr(conversation, "inquiry_id", None), conversation_id=conversation.id))
        db.commit()
    except Exception as exc:  # noqa: BLE001 -- the reply still goes out; log loudly
        db.rollback()
        log.error("wa_catalog_task_failed", tenant_id=tenant_id, error=str(exc)[:200])
    reply = ("Great choice. Our team will send you the dates, final price and a secure payment link here shortly."
             if wants_booking else "Sure. Someone from our team will reply here shortly.")
    queue(db, tenant_id, conversation, reply)
    return True
