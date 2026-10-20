"""The four WhatsApp templates HAIP sends around a booking (the "booking pack"), as Meta template components.

Texts come from the approved mock-up (docs/design/bookings-mockup/quotes.html, TEMPLATES). All are UTILITY, language
"en". Pay buttons are URL buttons whose link ends in {{1}}: the Razorpay short link's path ("i/AbC123") is passed per
send, after the fixed "https://rzp.io/". Document headers carry this guest's invoice or quote, attached per send.

``create_drafts`` only adds DRAFT rows to wa_templates. Nothing here talks to Meta: the owner opens each draft in the
template editor and submits it; a document header with no sample gets a generated sample PDF on Submit
(wa_template_sample_doc; Meta's review needs one).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.core.audit import append_audit

RZP_BASE = "https://rzp.io/"
LANGUAGE = "en"

QUOTE_PAYMENT = "ratha_quote_payment_v1"
BOOKING_CONFIRMED = "ratha_booking_confirmed_v1"
BALANCE_DUE = "ratha_balance_due_v1"
PAYMENT_RECEIVED = "ratha_payment_received_v1"


def _body(text: str, examples: list[str]) -> dict:
    return {"type": "BODY", "text": text, "example": {"body_text": [examples]}}


_DOC_HEADER = {"type": "HEADER", "format": "DOCUMENT"}
_PAY_EXAMPLE = [RZP_BASE + "i/AbC123xyz"]

PACK: list[dict] = [
    {
        "name": QUOTE_PAYMENT, "label": "Quote with payment link", "when": "An agent sends a quote with its payment link.",
        "header": "Document: the quote PDF",
        "components": [
            _DOC_HEADER,
            _body("Namaskara {{1}}, here is your Ratha plan.\n\n{{2}}\n{{3}} to {{4}} · {{5}} guests\n"
                  "Total {{6}} incl. GST. Tolls and parking at actuals.\n\n"
                  "Pay the {{7}} advance to confirm your dates. This quote is valid till {{8}}.",
                  ["Kiran", "Coorg 48-hour Retreat", "Fri, 30 Oct", "Sun, 1 Nov", "6", "₹89,880", "₹44,940", "Wed, 21 Oct"]),
            {"type": "BUTTONS", "buttons": [
                {"type": "URL", "text": "Pay advance", "url": RZP_BASE + "{{1}}", "example": _PAY_EXAMPLE},
                {"type": "QUICK_REPLY", "text": "Call me"},
            ]},
        ],
    },
    {
        "name": BOOKING_CONFIRMED, "label": "Booking confirmed + invoice", "when": "Razorpay reports the first payment.",
        "header": "Document: the invoice PDF",
        "components": [
            _DOC_HEADER,
            _body("Namaskara {{1}}, your Ratha trip is confirmed.\n\nBooking {{2}} · {{3}}\n{{4}} noon to {{5}} noon · {{6}}\n"
                  "We received {{7}}. The balance of {{8}} is due before travel begins.\n\n"
                  "Your invoice is attached. Our team will call you before the trip.",
                  ["Kiran", "#1050AB12", "Coorg, stay in Virajpet", "Fri, 30 Oct", "Sun, 1 Nov", "Ratha 1", "₹44,940", "₹44,940"]),
            {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Talk to us"}]},
        ],
    },
    {
        "name": BALANCE_DUE, "label": "Balance reminder with link",
        "when": "3 days before a balance is due (if switched on), or when an agent sends a payment link from the booking.",
        "header": "None",
        "components": [
            _body("Namaskara {{1}}, your Ratha trip on {{2}} is coming up. The balance of {{3}} is due by {{4}}.\n\n"
                  "You can pay it here.",
                  ["Kiran", "Fri, 30 Oct", "₹44,940", "Tue, 27 Oct"]),
            {"type": "BUTTONS", "buttons": [
                {"type": "URL", "text": "Pay balance", "url": RZP_BASE + "{{1}}", "example": _PAY_EXAMPLE},
            ]},
        ],
    },
    {
        "name": PAYMENT_RECEIVED, "label": "Payment received + updated invoice", "when": "Any later payment lands.",
        "header": "Document: the receipt with the updated balance",
        "components": [
            _DOC_HEADER,
            _body("Namaskara {{1}}, we received {{2}} for booking {{3}}. Thank you.\n\n{{4}}\n\n"
                  "Your updated invoice is attached.",
                  ["Kiran", "₹44,940", "#1050AB12", "Your trip is fully paid."]),
            {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Talk to us"}]},
        ],
    },
]
BY_NAME = {t["name"]: t for t in PACK}


def _model():
    from app.api.v1.endpoints.messaging import TemplateCategory, TemplateStatus, WATemplate
    return WATemplate, TemplateStatus, TemplateCategory


def statuses(db: Session, tenant_id: str) -> dict[str, Optional[str]]:
    """{template name: its status ("approved", "draft", ...) or None when the tenant has no such template}."""
    WATemplate, _, _ = _model()
    rows = db.query(WATemplate).filter(WATemplate.tenant_id == tenant_id, WATemplate.name.in_(list(BY_NAME))).all()
    out: dict[str, Optional[str]] = {n: None for n in BY_NAME}
    rank = {"approved": 5, "pending": 4, "draft": 3, "submission_failed": 2, "rejected": 1}
    for r in rows:
        st = getattr(r.status, "value", r.status)
        if out[r.name] is None or rank.get(st, 0) > rank.get(out[r.name] or "", 0):
            out[r.name] = st
    return out


def pack_out(db: Session, tenant_id: str) -> list[dict]:
    WATemplate, _, _ = _model()
    rows = {(r.name): r for r in db.query(WATemplate).filter(WATemplate.tenant_id == tenant_id, WATemplate.name.in_(list(BY_NAME)),
                                                             WATemplate.language == LANGUAGE).all()}
    out = []
    for t in PACK:
        row = rows.get(t["name"])
        body = next(c["text"] for c in t["components"] if c["type"] == "BODY")
        out.append({"name": t["name"], "label": t["label"], "when": t["when"], "header": t["header"], "body": body,
                    "buttons": [b["text"] for c in t["components"] if c["type"] == "BUTTONS" for b in c["buttons"]],
                    "template_id": row.id if row else None,
                    "status": getattr(row.status, "value", row.status) if row else None,
                    "rejection_reason": row.rejection_reason if row else None})
    return out


def create_drafts(db: Session, tenant_id: str, actor_id: Optional[str]) -> dict:
    """Add a DRAFT for each pack template the tenant does not have yet (same name + language). Safe to repeat."""
    WATemplate, TemplateStatus, TemplateCategory = _model()
    existing = {r.name for r in db.query(WATemplate.name).filter(WATemplate.tenant_id == tenant_id, WATemplate.language == LANGUAGE,
                                                                 WATemplate.name.in_(list(BY_NAME))).all()}
    created = []
    for t in PACK:
        if t["name"] in existing:
            continue
        db.add(WATemplate(tenant_id=tenant_id, name=t["name"], language=LANGUAGE, category=TemplateCategory.UTILITY,
                          status=TemplateStatus.DRAFT, components=[dict(c) for c in t["components"]]))
        created.append(t["name"])
    if created:
        append_audit(db, tenant_id=tenant_id, actor_user_id=actor_id, action="messaging.booking_pack_created",
                     target_type="wa_template", target_id=None, payload={"created": created})
    db.commit()
    return {"created": created, "templates": pack_out(db, tenant_id)}
