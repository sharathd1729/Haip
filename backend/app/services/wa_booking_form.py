"""Booking form in WhatsApp (WhatsApp step 3): a WhatsApp Flow the guest fills inside the chat (dates, guests, notes).

The workspace publishes HAIP's form once on its own WhatsApp Business account (Graph API: create flow, upload the
Flow JSON, publish; needs the token's whatsapp_business_management permission, the same one templates use). The id
is kept in the WhatsApp integration's config["booking_flow"]. The team sends it from the inbox as an interactive
"flow" message (inside the 24-hour window). The guest's answers come back as an ``nfm_reply``; ``apply`` writes the
dates and party size on the conversation's enquiry (the guest stated them, like chat-extracted dates) and the team
follows up. Static form: no data endpoint, nothing for Meta to call back.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
import structlog
from sqlalchemy.orm import Session

log = structlog.get_logger()

GRAPH = "https://graph.facebook.com/v20.0"
SCREEN = "TRIP"
TOKEN_PREFIX = "haip-booking:"
FLOW_NAME = "HAIP booking enquiry"

FLOW_JSON: dict[str, Any] = {
    "version": "6.0",
    "screens": [{
        "id": SCREEN, "title": "Plan your stay", "terminal": True, "success": True, "data": {},
        "layout": {"type": "SingleColumnLayout", "children": [
            {"type": "TextSubheading", "text": "Tell us your dates and we'll check availability."},
            {"type": "DatePicker", "name": "check_in", "label": "Check-in", "required": True},
            {"type": "DatePicker", "name": "check_out", "label": "Check-out", "required": True},
            {"type": "TextInput", "name": "adults", "label": "Adults", "input-type": "number", "required": True},
            {"type": "TextInput", "name": "children", "label": "Children", "input-type": "number", "required": False},
            {"type": "TextArea", "name": "notes", "label": "Anything we should know?", "required": False},
            {"type": "Footer", "label": "Send", "on-click-action": {"name": "complete", "payload": {
                "check_in": "${form.check_in}", "check_out": "${form.check_out}", "adults": "${form.adults}",
                "children": "${form.children}", "notes": "${form.notes}"}}},
        ]},
    }],
}


class BookingFormError(ValueError):
    pass


def _integration(db: Session, tenant_id: str):
    from app.models.integration import Integration

    return (db.query(Integration).filter(Integration.tenant_id == tenant_id, Integration.kind.in_(("whatsapp_meta", "whatsapp")),
                                          Integration.status == "active").first())


def status(db: Session, tenant_id: str) -> dict:
    row = _integration(db, tenant_id)
    flow = ((row.config or {}).get("booking_flow") or {}) if row else {}
    return {"connected": bool(row), "flow_id": flow.get("id"), "published": flow.get("status") == "PUBLISHED",
            "error": flow.get("error")}


def _meta_error(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error") or {}
        return str(err.get("error_user_msg") or err.get("message") or resp.text)[:300]
    except ValueError:
        return resp.text[:300]


def publish(db: Session, tenant_id: str) -> dict:
    """Create (once), upload and publish the form on the workspace's WhatsApp account. Idempotent."""
    from app.workers.tasks.whatsapp import _get_wa_access_token

    row = _integration(db, tenant_id)
    if row is None or not (row.config or {}).get("waba_id"):
        raise BookingFormError("Connect WhatsApp (with its Business Account ID) first.")
    token = _get_wa_access_token(db, tenant_id)
    if not token:
        raise BookingFormError("The WhatsApp access token is missing. Reconnect WhatsApp.")
    cfg = dict(row.config or {})
    flow = dict(cfg.get("booking_flow") or {})
    headers = {"Authorization": f"Bearer {token}"}

    def save(**changes):
        flow.update(changes)
        row.config = {**cfg, "booking_flow": flow}
        db.commit()

    with httpx.Client(timeout=20) as client:
        if not flow.get("id"):
            r = client.post(f"{GRAPH}/{cfg['waba_id']}/flows", headers=headers,
                            data={"name": FLOW_NAME, "categories": json.dumps(["APPOINTMENT_BOOKING"])})
            if r.status_code >= 400 or not r.json().get("id"):
                save(error=_meta_error(r))
                raise BookingFormError(f"Meta refused the form: {flow['error']}")
            save(id=str(r.json()["id"]), status="DRAFT", error=None)
        if flow.get("status") != "PUBLISHED":
            r = client.post(f"{GRAPH}/{flow['id']}/assets", headers=headers,
                            data={"name": "flow.json", "asset_type": "FLOW_JSON"},
                            files={"file": ("flow.json", json.dumps(FLOW_JSON), "application/json")})
            problems = (r.json() or {}).get("validation_errors") if r.status_code < 400 else None
            if r.status_code >= 400 or problems:
                save(error=_meta_error(r) if r.status_code >= 400 else json.dumps(problems)[:300])
                raise BookingFormError(f"Meta didn't accept the form: {flow['error']}")
            r = client.post(f"{GRAPH}/{flow['id']}/publish", headers=headers)
            if r.status_code >= 400:
                save(error=_meta_error(r))
                raise BookingFormError(f"Meta didn't publish the form: {flow['error']}")
            save(status="PUBLISHED", error=None)
    log.info("wa_booking_form_published", tenant_id=tenant_id, flow_id=flow["id"])
    return status(db, tenant_id)


def interactive_spec(db: Session, tenant_id: str, conversation_id: str) -> dict:
    st = status(db, tenant_id)
    if not st["published"]:
        raise BookingFormError("Publish the booking form first (Messaging > Growth).")
    return {"kind": "flow", "flow_id": st["flow_id"], "title": "Plan my stay", "flow_screen": SCREEN,
            "flow_token": f"{TOKEN_PREFIX}{conversation_id}"}


# ─── answers ────────────────────────────────────────────────────────────────────

def answers(msg: dict) -> dict | None:
    """The guest's answers from an nfm_reply, or None when the message isn't one of our forms."""
    i = msg.get("interactive") or {}
    if i.get("type") != "nfm_reply":
        return None
    try:
        data = json.loads((i.get("nfm_reply") or {}).get("response_json") or "{}")
    except (TypeError, ValueError):
        return None
    if not str(data.get("flow_token") or "").startswith(TOKEN_PREFIX):
        return None
    return data


def _date(v) -> date | None:
    s = str(v or "").strip()
    if s.isdigit():                       # older Flow versions send epoch milliseconds
        from datetime import UTC, datetime
        return datetime.fromtimestamp(int(s) / 1000, tz=UTC).date()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _count(v) -> int | None:
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= 50 else None


def parsed(data: dict) -> dict:
    ci, co = _date(data.get("check_in")), _date(data.get("check_out"))
    if ci and co and co <= ci:
        co = None
    return {"check_in": ci, "check_out": co, "adults": _count(data.get("adults")),
            "children": _count(data.get("children")), "notes": str(data.get("notes") or "").strip()[:500]}


def describe(msg: dict) -> str | None:
    """Readable text for the inbox: '📝 Booking form: 12 Dec → 15 Dec · 2 adults, 1 child'."""
    data = answers(msg)
    if data is None:
        return None
    p = parsed(data)
    parts = []
    if p["check_in"]:
        parts.append(p["check_in"].strftime("%d %b") + (f" → {p['check_out'].strftime('%d %b')}" if p["check_out"] else ""))
    people = []
    if p["adults"] is not None:
        people.append(f"{p['adults']} adult{'s' if p['adults'] != 1 else ''}")
    if p["children"]:
        people.append(f"{p['children']} child{'ren' if p['children'] != 1 else ''}")
    if people:
        parts.append(", ".join(people))
    text = "📝 Booking form: " + (" · ".join(parts) or "sent")
    return text + (f"\n{p['notes']}" if p["notes"] else "")


def apply(db: Session, tenant_id: str, guest, conversation, msg: dict) -> bool:
    """Write the answers on the conversation's enquiry and thank the guest. True when it was our form."""
    from app.models.inquiry import Inquiry
    from app.services import wa_catalog

    data = answers(msg)
    if data is None:
        return False
    p = parsed(data)
    inquiry = (db.query(Inquiry).filter_by(id=conversation.inquiry_id, tenant_id=tenant_id).first()
               if getattr(conversation, "inquiry_id", None) else None)
    if inquiry is not None:
        if p["check_in"]:
            inquiry.check_in = p["check_in"].isoformat()
            inquiry.check_out = p["check_out"].isoformat() if p["check_out"] else inquiry.check_out
            inquiry.dates_from_chat = True    # the guest's own words; a voice-call date still wins later
        if p["adults"] is not None:
            inquiry.adults = p["adults"]
        if p["children"] is not None:
            inquiry.children = p["children"]
        if p["notes"]:
            inquiry.special_requests = ((inquiry.special_requests or "") + f"\n[Booking form] {p['notes']}").strip()[:4000]
        db.commit()
    else:
        log.warning("wa_booking_form_no_inquiry", tenant_id=tenant_id, conversation_id=conversation.id)
    wa_catalog.queue(db, tenant_id, conversation, "Thank you! We've got your dates. Our team will confirm availability here shortly.",
                     sender_name="Booking form", source="booking_form")
    return True
