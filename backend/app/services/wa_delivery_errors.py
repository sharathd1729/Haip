"""Why Meta did not deliver a WhatsApp message, in words a person can act on, and where it is recorded.

Meta reports a failed delivery on the status webhook as ``errors: [{code, title}]``. Before this the inbox showed
"131026: Message undeliverable" and a bare Retry, which can never work for a number that is not on WhatsApp.
``describe`` turns the code into a sentence (+ what to do); ``record`` writes it on the message and on Workflows ›
Activity (``playbook_actions``): the playbook's own row when a playbook sent it, else one ``failed`` row for a person's
template send (``playbook_key = "manual_template"``), so undeliverable numbers show in one place.
Meta never says "blocked" outright: a guest who blocked the business also comes back as 131026.
"""

from __future__ import annotations

import structlog
from sqlalchemy.orm import Session

log = structlog.get_logger()

MANUAL_TEMPLATE = "manual_template"

# Meta Cloud API error code -> (plain reason, next step). Codes: developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes
REASONS: dict[int, tuple[str, str]] = {
    131026: (
        "This number isn't on WhatsApp, or it can't receive messages from businesses (it may have blocked us).",
        "Call the guest, or reply on Instagram if they write there.",
    ),
    131047: (
        "The guest's 24-hour WhatsApp window is closed, so only an approved template can go.",
        "Send a template instead.",
    ),
    131049: (
        "Meta held this marketing message back (the guest already got many business messages).",
        "Use a utility template, or call.",
    ),
    131050: ("The guest turned off marketing messages from businesses.", "Use a utility template, or call."),
    130472: (
        "Meta held this marketing message back (the guest's number is in a Meta test group).",
        "Use a utility template, or call.",
    ),
    131056: ("Too many messages to this number in a short time.", "Wait a few minutes, then try again."),
    131048: (
        "Meta is limiting our sends because messages were blocked or reported as spam.",
        "Check the WhatsApp quality rating before sending more.",
    ),
    131042: ("The WhatsApp business account has a payment problem.", "Ask the owner to fix billing in Meta Business."),
    131031: ("The WhatsApp business account is locked.", "Ask the owner to check Meta Business."),
    132000: ("The template's values don't match what Meta approved.", "Pick the template again and fill every value."),
    132001: ("This template is not approved in that language on Meta.", "Check the template in WhatsApp › Templates."),
    132012: (
        "The template's values are in the wrong format for Meta.",
        "Pick the template again and fill every value.",
    ),
}


def _code(errors: list) -> int | None:
    for e in errors or []:
        try:
            return int((e or {}).get("code"))
        except (TypeError, ValueError):
            continue
    return None


def describe(errors: list) -> str:
    """One line for Message.delivery_error: the plain reason, the next step, and Meta's code at the end."""
    code = _code(errors)
    if code in REASONS:
        reason, step = REASONS[code]
        return f"{reason} {step} (Meta {code})"
    raw = "; ".join(f"{e.get('code')}: {e.get('title', '')}" for e in errors or [] if isinstance(e, dict))
    return f"WhatsApp did not deliver this message ({raw})." if raw else "WhatsApp did not deliver this message."


def record(db: Session, tenant_id: str, message, errors: list) -> None:
    """Put the failure on Workflows › Activity. Does not commit (the webhook's transaction does)."""
    from app.models.conversation import Conversation
    from app.models.lead_workflow import PlaybookAction

    reason = describe(errors)
    meta = message.channel_metadata if isinstance(message.channel_metadata, dict) else {}
    action = db.query(PlaybookAction).filter_by(tenant_id=tenant_id, message_id=message.id).first()
    if action is not None:
        action.status, action.reason = "failed", reason
        return
    if not meta.get("template_name") or getattr(message, "sender_kind", None) not in ("human", None):
        return  # a person's free text shows its reason on the message; system/campaign sends have their own reports
    conv = db.query(Conversation).filter_by(id=message.conversation_id, tenant_id=tenant_id).first()
    db.add(
        PlaybookAction(
            tenant_id=tenant_id,
            playbook_key=MANUAL_TEMPLATE,
            action="wa_template",
            status="failed",
            reason=reason,
            message_id=message.id,
            guest_id=getattr(conv, "guest_id", None),
            inquiry_id=getattr(conv, "inquiry_id", None),
            template_name=(meta.get("template_name") or "")[:100],
            recipient_user_id=message.sender_id,
            payload={"meta_code": _code(errors)},
        )
    )
    log.info("wa_undeliverable_recorded", tenant_id=tenant_id, message_id=message.id, code=_code(errors))
