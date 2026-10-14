"""
WhatsApp campaign delivery tracking.

Records what happened to every message of a campaign, applies Meta's status
callbacks (sent / delivered / read / failed) in the right order, turns Meta's
numeric error codes into words a person can act on, and builds the report.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.wa_campaign_recipient import WACampaignRecipient as Recipient

log = structlog.get_logger()

# A status only moves forward. Failed is below "sent" so a real later status
# (which carries the message id, so it can only be a genuine one) wins over it.
RANK = {"failed": -1, "queued": 0, "sent": 1, "delivered": 2, "read": 3}


# ─── Meta error codes ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ErrorInfo:
    code: str
    reason: str
    group: str
    hint: Optional[str] = None


# code -> (group, plain reason, what to do). Codes from Meta's WhatsApp Cloud
# API error reference; anything not listed falls through to Meta's own text.
_META_ERRORS: dict[str, tuple[str, str, Optional[str]]] = {
    "131026": ("not_reachable", "Not delivered: the number isn't on WhatsApp, or the guest can't receive this message.",
               "Check the number. Remove it from the list if it isn't a WhatsApp user."),
    "131049": ("marketing_limit", "Meta held back this marketing message to protect the guest's experience.",
               "Meta caps how many marketing messages one person receives. Try this guest again in a few days."),
    "131050": ("opted_out", "The guest has opted out of marketing messages from you.",
               "Don't message them again with marketing templates."),
    "131047": ("not_reachable", "The 24-hour reply window is closed: this guest hasn't messaged in the last 24 hours.",
               "Send an approved template instead of a normal message."),
    "131030": ("account", "This WhatsApp number can only message people on its allowed list (test mode).",
               "Add the recipient in Meta's WhatsApp API Setup, or move to a live number."),
    "131048": ("rate_limit", "WhatsApp is limiting this number for spam-like activity.",
               "Slow down, and check your quality rating in Meta Business Manager."),
    "131056": ("rate_limit", "Too many messages to the same guest in a short time.", "Try again later."),
    "130429": ("rate_limit", "Sending too fast — Meta's throughput limit was hit.", "The campaign can be resumed later."),
    "131042": ("account", "Your WhatsApp Business account has a payment problem.", "Fix the payment method in Meta Business Manager."),
    "131031": ("account", "Your WhatsApp Business account is locked.", "Check Meta Business Manager for the reason."),
    "131005": ("account", "Access denied for this WhatsApp Business account.", "Reconnect WhatsApp under Settings → Integrations."),
    "131021": ("not_reachable", "The recipient is the same as the sending number.", None),
    "133010": ("account", "The sending phone number isn't registered with WhatsApp.", "Check the number in Meta Business Manager."),
    "190":    ("account", "The WhatsApp connection has expired.", "Reconnect WhatsApp under Settings → Integrations."),
    "132000": ("template", "The message's variables don't match the template.", "Check the variable mapping for this campaign."),
    "132001": ("template", "This template doesn't exist in Meta for that language.", "Check the template name and language."),
    "132005": ("template", "The message became too long once the variables were filled in.", "Use shorter values, or shorten the template."),
    "132007": ("template", "Meta says this template breaks its content policy.", "Edit the template and resubmit it."),
    "132012": ("template", "A variable's value is in the wrong format.", "Check the variable mapping for this campaign."),
    "132015": ("template", "This template is paused by Meta because of low quality.", "Wait, or edit and resubmit it."),
    "132016": ("template", "This template has been disabled by Meta.", "Create a new template."),
    "131052": ("template", "Meta couldn't download the header file.", "Re-upload the header media and try again."),
    "131053": ("template", "Meta couldn't accept the header file.", "Re-upload the header media and try again."),
    "131000": ("other", "Meta had a temporary problem.", "Try again."),
    "131016": ("other", "WhatsApp was temporarily unavailable.", "Try again."),
    "100":    ("template", "Meta rejected part of the message.", "Check the template and its variables."),
}

# Our own codes (a message that never reached Meta).
HAIP_VARIABLE = "HAIP_VARIABLE"
HAIP_SEND = "HAIP_SEND"

GROUP_LABELS = {
    "not_reachable": "Number can't receive it",
    "marketing_limit": "Meta's marketing limit",
    "opted_out": "Opted out",
    "rate_limit": "Sending too fast",
    "account": "WhatsApp account",
    "template": "Template problem",
    "missing_value": "Missing value",
    "other": "Other",
}


def describe_error(code: Any, message: Optional[str] = None) -> ErrorInfo:
    key = str(code) if code is not None else ""
    if key == HAIP_VARIABLE:
        return ErrorInfo(key, message or "A variable had no value.", "missing_value",
                         "Give that variable a fallback in the campaign, or fix the guest's details.")
    if key == HAIP_SEND:
        return ErrorInfo(key, message or "The message couldn't be sent.", "other", "Try again.")
    if key in _META_ERRORS:
        group, reason, hint = _META_ERRORS[key]
        return ErrorInfo(key, reason, group, hint)
    text = (message or "").strip() or (f"Meta reported error {key}." if key else "The message failed.")
    return ErrorInfo(key, text[:500], "other", None)


def error_from_exception(exc: Exception) -> tuple[Optional[str], str]:
    """(Meta error code, message) from a failed send. The Meta adapter raises
    httpx.HTTPStatusError with Meta's JSON body on the response; without
    reading it every failure is just '400 Bad Request'."""
    resp = getattr(exc, "response", None)
    if resp is not None:
        try:
            err = (resp.json() or {}).get("error") or {}
        except Exception:  # noqa: BLE001 - a non-JSON error body is still an error
            err = {}
        if err:
            details = (err.get("error_data") or {}).get("details")
            return (str(err["code"]) if err.get("code") is not None else None,
                    str(details or err.get("message") or exc)[:500])
    return None, str(exc)[:500]


def is_retryable(exc: Exception) -> bool:
    """Whether trying the same send again could work. A 4xx from Meta (bad
    number, closed window, wrong template values) is a verdict on this very
    message and will come back the same every time; only Meta being busy or
    down (5xx, 429) or a network error is worth another go."""
    resp = getattr(exc, "response", None)
    if resp is not None:
        status = getattr(resp, "status_code", 0) or 0
        return status >= 500 or status == 429
    return True


def failure_text(exc: Exception) -> str:
    """What to show a person when a send failed: Meta's reason in plain words,
    the code for support, and what to do next."""
    code, message = error_from_exception(exc)
    info = describe_error(code, message)
    text = info.reason
    if info.code and not info.code.startswith("HAIP_"):
        text += f" (Meta error {info.code})"
    if info.hint:
        text += f" {info.hint}"
    return text[:500]


# ─── Recording a send ────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_or_create_recipient(db: Session, tenant_id: str, campaign_id: str, subscriber: Any) -> Recipient:
    row = db.query(Recipient).filter_by(campaign_id=campaign_id, phone=subscriber.phone).first()
    if row:
        return row
    row = Recipient(
        tenant_id=tenant_id, campaign_id=campaign_id,
        subscriber_id=getattr(subscriber, "id", None) if not getattr(subscriber, "guest_id", None) else None,
        guest_id=getattr(subscriber, "guest_id", None),
        phone=subscriber.phone, name=getattr(subscriber, "name", None), status="queued",
    )
    db.add(row)
    db.flush()
    return row


def already_sent(row: Recipient) -> bool:
    """True once Meta accepted the message -- a retried or resumed run must not
    send it again."""
    return row.status in ("sent", "delivered", "read")


# Failures a second attempt can't fix: asking again for someone who isn't on
# WhatsApp or who opted out only wastes a send (and hurts the quality rating).
_FINAL_GROUPS = ("not_reachable", "opted_out", "marketing_limit")


def should_skip(row: Recipient) -> bool:
    """Leave this guest alone on a retried or resumed run."""
    if already_sent(row):
        return True
    return row.status == "failed" and describe_error(row.error_code, row.error_reason).group in _FINAL_GROUPS


def mark_sent(row: Recipient, response: Optional[dict]) -> None:
    wamid = None
    try:
        wamid = ((response or {}).get("messages") or [{}])[0].get("id")
    except (AttributeError, IndexError, TypeError):
        pass
    row.status = "sent"
    row.wa_message_id = wamid
    row.sent_at = _now()
    row.error_code = None
    row.error_reason = None
    row.failed_at = None


def mark_failed(row: Recipient, code: Optional[str], message: Optional[str]) -> ErrorInfo:
    info = describe_error(code, message)
    row.status = "failed"
    row.error_code = info.code or None
    row.error_reason = info.reason
    row.failed_at = _now()
    return info


# ─── Status callbacks ────────────────────────────────────────────────────────

def _callback_time(obj: dict) -> datetime:
    try:
        return datetime.fromtimestamp(int(obj.get("timestamp")), tz=timezone.utc)
    except (TypeError, ValueError):
        return _now()


def apply_status_callback(db: Session, tenant_id: str, status_obj: dict) -> bool:
    """Apply one Meta status callback to the campaign recipient it belongs to.

    Returns True when the message was a campaign message (so the caller should
    not look for an inbox message with the same id), False otherwise."""
    wamid = status_obj.get("id")
    status = status_obj.get("status")
    if not wamid or status not in ("sent", "delivered", "read", "failed"):
        return False

    row = db.query(Recipient).filter_by(tenant_id=tenant_id, wa_message_id=wamid).first()
    if not row:
        return False

    when = _callback_time(status_obj)
    if status == "failed":
        if row.status in ("delivered", "read"):
            return True                       # it did arrive; a stray failure doesn't undo that
        errors = status_obj.get("errors") or [{}]
        first = errors[0] if isinstance(errors[0], dict) else {}
        details = (first.get("error_data") or {}).get("details")
        mark_failed(row, first.get("code"), details or first.get("message") or first.get("title"))
        row.failed_at = when
    elif RANK[status] > RANK.get(row.status, 0):
        row.status = status
        row.error_code = None
        row.error_reason = None
        row.failed_at = None
        if row.sent_at is None:
            row.sent_at = when
        if status in ("delivered", "read") and row.delivered_at is None:
            row.delivered_at = when
        if status == "read":
            row.read_at = when
    else:
        return True                           # late or repeated callback

    refresh_campaign_counters(db, tenant_id, row.campaign_id)
    return True


# ─── Audience ────────────────────────────────────────────────────────────────

def audience_subscribers(db: Session, tenant_id: str, audience_filter: Optional[dict]) -> list:
    """Who a campaign goes to: opted-in subscribers, narrowed by tag (any of
    them) and by source. One rule for the runner and for the audience count
    the campaign form shows, so the number you see is the number that is sent."""
    from app.api.v1.endpoints.messaging import WASubscriber
    af = audience_filter or {}
    subs = db.query(WASubscriber).filter_by(tenant_id=tenant_id, opted_in=True).all()
    if af.get("tags"):
        wanted = {t.lower() for t in af["tags"]}
        subs = [s for s in subs if any(t.lower() in wanted for t in (s.tags or []))]
    if af.get("source"):
        wanted_src = {x.lower() for x in af["source"]}
        subs = [s for s in subs if (s.source or "").lower() in wanted_src]
    return subs


def audience_members(db: Session, tenant_id: str, audience_filter: Optional[dict]) -> list:
    """The people a campaign goes to, whichever kind of audience it has: CRM
    leads (audience_filter["type"] == "leads") or the imported subscriber list."""
    if (audience_filter or {}).get("type") == "leads":
        from app.services import wa_lead_audience
        return wa_lead_audience.resolve(db, tenant_id, audience_filter).members
    return audience_subscribers(db, tenant_id, audience_filter)


# ─── Counters + report ───────────────────────────────────────────────────────

def status_counts(db: Session, campaign_id: str) -> dict[str, int]:
    # Sessions here run with autoflush off: without this the counts miss
    # whatever the caller just changed and lag one event behind.
    db.flush()
    rows = (
        db.query(Recipient.status, func.count(Recipient.id))
        .filter(Recipient.campaign_id == campaign_id)
        .group_by(Recipient.status)
        .all()
    )
    counts = {"queued": 0, "sent": 0, "delivered": 0, "read": 0, "failed": 0}
    for status, n in rows:
        counts[status] = n
    return counts


def cumulative(counts: dict[str, int]) -> dict[str, int]:
    """Cumulative the way people read them: everything Meta accepted was
    sent; everything read was also delivered."""
    return {
        "total": sum(counts.values()),
        "sent": counts["sent"] + counts["delivered"] + counts["read"],
        "delivered": counts["delivered"] + counts["read"],
        "read": counts["read"],
        "failed": counts["failed"],
        "queued": counts["queued"],
    }


def refresh_campaign_counters(db: Session, tenant_id: str, campaign_id: str) -> None:
    from app.api.v1.endpoints.messaging import WACampaign
    campaign = db.query(WACampaign).filter_by(id=campaign_id, tenant_id=tenant_id).first()
    if not campaign:
        return
    c = cumulative(status_counts(db, campaign_id))
    campaign.sent_count = str(c["sent"])
    campaign.delivered_count = str(c["delivered"])
    campaign.read_count = str(c["read"])
    campaign.failed_count = str(c["failed"])


def failure_breakdown(db: Session, campaign_id: str) -> list[dict]:
    rows = (
        db.query(Recipient.error_code, Recipient.error_reason, func.count(Recipient.id))
        .filter(Recipient.campaign_id == campaign_id, Recipient.status == "failed")
        .group_by(Recipient.error_code, Recipient.error_reason)
        .all()
    )
    out = []
    for code, reason, n in rows:
        info = describe_error(code, reason)
        out.append({
            "code": code, "reason": reason or info.reason, "group": info.group,
            "group_label": GROUP_LABELS.get(info.group, "Other"), "hint": info.hint, "count": n,
        })
    return sorted(out, key=lambda r: -r["count"])


# A guest's WhatsApp message counts as a reply to the campaign when it arrives after the campaign message went out and within this
# many days. Later messages are ordinary conversation, not a response to the campaign.
REPLY_WINDOW_DAYS = 7


def replies(db: Session, tenant_id: str, campaign_id: str) -> dict[str, datetime]:
    """recipient id -> when that guest first wrote back on WhatsApp after the campaign message (within REPLY_WINDOW_DAYS).

    Read from the inbox, which is where replies land, matched on the guest's phone number; no extra tracking is stored.
    A recipient whose number matches no guest, or who never wrote, simply has no entry."""
    from datetime import timedelta
    from app.models.conversation import ChannelType, Conversation, Message
    from app.models.guest import Guest

    db.flush()
    rows = (
        db.query(Recipient.id, Recipient.sent_at, func.min(Message.created_at))
        .join(Guest, (Guest.tenant_id == Recipient.tenant_id) & (Guest.phone == Recipient.phone))
        .join(Conversation, (Conversation.guest_id == Guest.id) & (Conversation.tenant_id == Recipient.tenant_id) & (Conversation.channel == ChannelType.WHATSAPP))
        .join(Message, (Message.conversation_id == Conversation.id) & (Message.direction == "inbound") & (Message.created_at >= Recipient.sent_at))
        .filter(Recipient.tenant_id == tenant_id, Recipient.campaign_id == campaign_id, Recipient.sent_at.isnot(None))
        .group_by(Recipient.id, Recipient.sent_at)
        .all()
    )
    out: dict[str, datetime] = {}
    for rid, sent_at, first in rows:
        a = sent_at if sent_at.tzinfo else sent_at.replace(tzinfo=timezone.utc)
        b = first if first.tzinfo else first.replace(tzinfo=timezone.utc)
        if b - a <= timedelta(days=REPLY_WINDOW_DAYS):
            out[rid] = b
    return out


def recipient_dict(r: Recipient, replied_at: Optional[datetime] = None) -> dict:
    def iso(v): return v.isoformat() if v else None
    return {
        "id": r.id, "phone": r.phone, "name": r.name, "status": r.status,
        "error_code": r.error_code, "error_reason": r.error_reason,
        "sent_at": iso(r.sent_at), "delivered_at": iso(r.delivered_at),
        "read_at": iso(r.read_at), "failed_at": iso(r.failed_at),
        "replied": replied_at is not None, "replied_at": iso(replied_at),
    }


def recipients_query(db: Session, tenant_id: str, campaign_id: str, status: Optional[str] = None, search: Optional[str] = None):
    q = db.query(Recipient).filter(Recipient.tenant_id == tenant_id, Recipient.campaign_id == campaign_id)
    if status == "delivered":       # cumulative, like the summary tiles
        q = q.filter(Recipient.status.in_(("delivered", "read")))
    elif status == "sent":
        q = q.filter(Recipient.status.in_(("sent", "delivered", "read")))
    elif status == "replied":       # needs the reply map: the caller filters by id (see campaign_report)
        pass
    elif status:
        q = q.filter(Recipient.status == status)
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(Recipient.phone.ilike(like) | Recipient.name.ilike(like))
    return q
