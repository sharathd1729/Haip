"""What happens after an Instagram automation's final message (Instagram Automations v2, phases 3 and 4).

`after_final` runs wherever the final message went out in an open chat: it offers "Suggest more" (a quick reply that
shows the workspace's stays or packages as swipeable cards) and starts the follow-up sequence (services/ig_sequence.py).

Cards never show prices, whatever the workspace's price rule: name, a short line (bedrooms and guests, or the
package summary), a photo when there is one, and "I'm interested". That tap thanks the guest, writes the choice on
their enquiry and leaves the chat to the team. Packages come only through sales_gateway (published, guest-facing data).
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models.automation import AutomationRule
from app.services import ig_automation as engine

logger = logging.getLogger(__name__)

MAX_CARDS = 10


def after_final(
    db: Session,
    tenant_id: str,
    rule: AutomationRule,
    adapter,
    *,
    recipient_id: str,
    guest_id: str | None,
    conversation_id: str | None,
) -> None:
    """Offer "Suggest more" (when on) and start the follow-ups. Commits what it writes."""
    from app.services import ig_sequence

    cfg = (rule.action_config or {}).get("suggest_more") or {}
    if cfg.get("enabled") and adapter is not None and guest_id:
        text = cfg.get("prompt") or "Want to see our other stays?"
        quick = [
            {
                "content_type": "text",
                "title": (cfg.get("button_title") or "More stays")[:20],
                "payload": engine._payload(rule.id, "more"),
            }
        ]
        try:
            result = adapter.send_quick_replies(recipient_id, text, quick)
            engine._record(db, tenant_id, conversation_id, text, result, rule.id)
            db.commit()
        except Exception as exc:  # noqa: BLE001 -- the offer is extra; the final message already went out
            logger.warning("ig_suggest_offer_failed rule=%s: %s", rule.id, exc)
    ig_sequence.begin(rule, tenant_id, recipient_id=recipient_id, guest_id=guest_id, conversation_id=conversation_id)


def _photo(photos) -> str | None:
    for p in photos or []:
        url = p if isinstance(p, str) else (p.get("url") or p.get("src")) if isinstance(p, dict) else None
        if isinstance(url, str) and url.startswith("https://"):
            return url
    return None


def items(db: Session, tenant_id: str, source: str) -> list[dict]:
    """[{title, subtitle, image_url?}] for the cards, in a stable order (the "ask:<n>" index points into it)."""
    out: list[dict] = []
    if source == "packages":
        from app.services import sales_gateway

        res = sales_gateway.list_packages(db, tenant_id, include_rates=False)
        for pkg in (res.data or [])[:MAX_CARDS] if res.ok else []:
            out.append(
                {"title": str(pkg.get("name") or "Package")[:80], "subtitle": str(pkg.get("summary") or "")[:80]}
            )
        return out
    from app.models.property import Property

    for p in (
        db.query(Property)
        .filter(Property.tenant_id == tenant_id, Property.is_active.is_(True))
        .order_by(Property.name)
        .limit(MAX_CARDS)
        .all()
    ):
        if p.vehicle_type or p.seats:
            line = f"Up to {p.seats} guests" if p.seats else "Caravan"
        else:
            line = (
                f"{p.bedrooms or 1} bedroom{'s' if (p.bedrooms or 1) != 1 else ''} · up to {p.max_adults or 2} guests"
            )
        if p.city:
            line = f"{line} · {p.city}"
        card = {"title": (p.vehicle_name or p.name)[:80], "subtitle": line[:80]}
        image = _photo(p.photos)
        if image:
            card["image_url"] = image
        out.append(card)
    return out


def route(
    db: Session,
    tenant_id: str,
    rule: AutomationRule,
    step: str,
    recipient_id: str,
    guest_id: str | None,
    conversation_id: str | None,
    guest=None,
) -> bool:
    """Taps engine.handle_payload passes on: "start" (a welcome question or menu item linked to this automation: run it
    as if it was triggered in an open chat), "more" and "ask:<n>" (suggest more). Always True: the tap was ours."""
    if step == "start":
        engine.start(
            db,
            tenant_id,
            rule,
            recipient_id=recipient_id,
            guest_id=guest_id,
            conversation_id=conversation_id,
            guest=guest,
        )
        return True
    adapter = engine._adapter(db, tenant_id)
    if adapter is None:
        return True
    return handle(
        db,
        tenant_id,
        rule,
        step,
        adapter,
        recipient_id=recipient_id,
        guest_id=guest_id,
        conversation_id=conversation_id,
    )


def handle(
    db: Session,
    tenant_id: str,
    rule: AutomationRule,
    step: str,
    adapter,
    *,
    recipient_id: str,
    guest_id: str | None,
    conversation_id: str | None,
) -> bool:
    """A tap on "More stays" (step "more") or "I'm interested" (step "ask:<n>"). True (it was ours). Commits."""
    cfg = (rule.action_config or {}).get("suggest_more") or {}
    cards = items(db, tenant_id, cfg.get("source") or "stays")
    try:
        if step == "more":
            if not cards:
                text = "Our team will share more options with you here shortly."
                result = adapter.send_text(recipient_id, text)
            else:
                elements = [
                    {
                        **c,
                        "buttons": [
                            {
                                "type": "postback",
                                "title": "I'm interested",
                                "payload": engine._payload(rule.id, f"ask:{i}"),
                            }
                        ],
                    }
                    for i, c in enumerate(cards)
                ]
                result = adapter.send_cards(recipient_id, elements)
                text = "Sent options: " + ", ".join(c["title"] for c in cards)
            engine._record(db, tenant_id, conversation_id, text, result, rule.id)
            engine.log_event(db, tenant_id, rule.id, "cards_sent", guest_id, detail=str(len(cards)))
        else:
            index = int(step.split(":", 1)[1])
            name = cards[index]["title"] if index < len(cards) else "that option"
            text = f"Great choice! Our team will share the details for {name} with you here shortly."
            result = adapter.send_text(recipient_id, text)
            engine._record(db, tenant_id, conversation_id, text, result, rule.id)
            engine.log_event(db, tenant_id, rule.id, "card_interest", guest_id, detail=name[:300])
            _note_interest(db, tenant_id, conversation_id, name)
    except Exception as exc:  # noqa: BLE001
        engine.log_event(db, tenant_id, rule.id, "dm_failed", guest_id, detail=f"suggest more: {exc}"[:300])
    db.commit()
    return True


def _note_interest(db: Session, tenant_id: str, conversation_id: str | None, name: str) -> None:
    """Write the guest's pick on their enquiry so the team sees it in Leads360."""
    from app.models.conversation import Conversation
    from app.models.inquiry import Inquiry

    conv = (
        db.query(Conversation).filter_by(id=conversation_id, tenant_id=tenant_id).first() if conversation_id else None
    )
    inquiry = (
        db.query(Inquiry).filter_by(id=conv.inquiry_id, tenant_id=tenant_id).first()
        if conv is not None and conv.inquiry_id
        else None
    )
    if inquiry is None:
        return
    note = f"Interested in: {name} (Instagram)"
    if note not in (inquiry.special_requests or ""):
        inquiry.special_requests = f"{inquiry.special_requests}\n{note}" if inquiry.special_requests else note
