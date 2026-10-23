"""The WhatsApp templates the lead playbooks send (the "lead pack"), as Meta template components, plus the plain-text
versions used while the guest's 24-hour window is open (no template needed then).

A phone call does not open WhatsApp's 24-hour window, so most missed-call / no-answer messages go out as a template. All
are UTILITY (transactional: about the call the guest just made or missed), language "en". Wording changes need a new
name (``_v2``): Meta reviews each name once.

``create_drafts`` only adds DRAFT rows to wa_templates. Nothing here talks to Meta: the owner opens each draft in the
template editor and submits it (same as the booking pack).
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.core.audit import append_audit

LANGUAGE = "en"

MISSED_CALL = "haip_missed_call_v1"
TRIED_CALLING = "haip_tried_calling_v1"
# To the TEAM (staff personal numbers, lead_alert_service): no guest phone number in any of them.
STAFF_ALERT = "haip_staff_lead_alert_v1"
STAFF_ESCALATION = "haip_staff_escalation_v1"
STAFF_DIGEST = "haip_staff_digest_v1"
# Follow-ups to the GUEST (lead_followup_service, playbooks P5 / P6 / P8).
QUOTE_FOLLOWUP = "haip_quote_followup_v1"
QUOTE_FINAL = "haip_quote_final_v1"
CHECKIN = "haip_checkin_v1"
REENGAGE = "haip_reengage_v1"                 # MARKETING: only to guests who agreed to offers
# Send package (package_share_service): a person sends a published package to a lead whose 24-hour window is closed.
PACKAGE_SHARE = "haip_package_share_v1"
# To owners / managers (analyst.delivery): the report PDF as the header, the signed view-only page as the URL button.
ANALYST_BRIEF = "haip_analyst_brief_v1"
APP_URL_TOKEN = "{APP_URL}"                    # replaced with FRONTEND_URL when the draft is created

# Quick-reply button texts. The webhook matches a tap on these (lead_playbook_engine.on_guest_button).
BTN_CALL_ME_BACK = "Call me back"
BTN_CALL_ME_LATER = "Call me later"
BTN_SHARE_HERE = "Share details here"
# Staff alert buttons; each send carries its own payload "la:{action_id}:ack|take" (lead_alert_sender).
BTN_ACK = "Acknowledge"
BTN_TAKE = "I'll take it"
BTN_QUESTION = "I have a question"
BTN_HOLD = "Yes, hold them"
BTN_NOT_NOW = "Not now"
BTN_STILL_PLANNING = "Still planning"
BTN_SHOW_OPTIONS = "Show me options"
BTN_STOP_PROMOS = "Stop promotions"
ACK_INDEX, TAKE_INDEX = 0, 1


def _body(text: str, examples: list[str]) -> dict:
    return {"type": "BODY", "text": text, "example": {"body_text": [examples]}}


def _quick(*texts: str) -> dict:
    return {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": t} for t in texts]}


PACK: list[dict] = [
    {
        "name": MISSED_CALL, "label": "Missed call", "when": "A guest called and nobody picked up (playbook P1).",
        "components": [
            _body("Hi {{1}}, sorry we missed your call to {{2}}. Reply here with your dates and group size and we'll help "
                  "right away. We'll also call you back {{3}}.",
                  ["Kiran", "Ratha", "shortly"]),
            _quick(BTN_CALL_ME_BACK, BTN_SHARE_HERE),
        ],
    },
    {
        "name": TRIED_CALLING, "label": "We tried calling", "when": "An agent called a lead and nobody picked up (playbook P2).",
        "components": [
            _body("Hi {{1}}, {{2}} from {{3}} just tried calling you about your enquiry. Maybe you're busy. We can share "
                  "the details and proposal right here on WhatsApp.",
                  ["Kiran", "Asha", "Ratha"]),
            _quick(BTN_SHARE_HERE, BTN_CALL_ME_LATER),
        ],
    },
    {
        "name": STAFF_ALERT, "label": "Team alert", "when": "A lead waits too long: first alert to the lead's owner (P3, P4).",
        "components": [
            _body("HAIP alert ({{1}}): {{2}} needs the team. {{3}}. Waiting {{4}}, owner {{5}}. Open My day in HAIP to act "
                  "on it.",
                  ["Late", "Kiran, new lead", "Coorg, 6 guests, 30 Oct", "25 min", "Asha"]),
            _quick(BTN_ACK, BTN_TAKE),
        ],
    },
    {
        "name": STAFF_ESCALATION, "label": "Team escalation", "when": "Still waiting: the manager, then the owner (P3, P4).",
        "components": [
            _body("HAIP escalation ({{1}}): {{2}} still needs the team. {{3}}. Waiting {{4}}; {{5}} has not acted yet. "
                  "Open My day in HAIP to act on it.",
                  ["Urgent", "Kiran, new lead", "Coorg, 6 guests, 30 Oct", "1 h 10 min", "Asha"]),
            _quick(BTN_ACK, BTN_TAKE),
        ],
    },
    {
        "name": STAFF_DIGEST, "label": "Morning summary", "when": "After quiet hours: one message instead of the alerts held overnight.",
        "components": [
            _body("Good morning. {{1}} leads waited overnight for the team. The oldest is {{2}}, waiting {{3}}. Open My "
                  "day in HAIP to act on them.",
                  ["4", "Kiran", "9 h"]),
        ],
    },
    {
        "name": QUOTE_FOLLOWUP, "label": "Proposal follow-up", "when": "6 hours after a proposal, if the guest has not replied (P5).",
        "components": [
            _body("Hi {{1}}, just checking you received the proposal for {{2}} we shared on {{3}}. Happy to answer any "
                  "questions or adjust it for you.",
                  ["Kiran", "the Coorg 48-hour retreat", "Mon, 19 Oct"]),
            _quick(BTN_QUESTION, BTN_CALL_ME_BACK),
        ],
    },
    {
        "name": QUOTE_FINAL, "label": "Proposal last call", "when": "Day 7 after a proposal with no reply (P5).",
        "components": [
            _body("Hi {{1}}, your proposal for {{2}} is valid until {{3}}. Shall we hold these dates for you?",
                  ["Kiran", "the Coorg 48-hour retreat", "Wed, 21 Oct"]),
            _quick(BTN_HOLD, BTN_NOT_NOW),
        ],
    },
    {
        "name": CHECKIN, "label": "Check-in", "when": "Day 3 after our last message with no reply, before any proposal (P6).",
        "components": [
            _body("Hi {{1}}, following up on your enquiry about {{2}}. Are you still planning the trip? Reply with your "
                  "dates and we'll check availability.",
                  ["Kiran", "a Ratha trip"]),
            _quick(BTN_STILL_PLANNING, BTN_NOT_NOW),
        ],
    },
    {
        "name": PACKAGE_SHARE, "label": "Package details", "when": "A person taps Send package and the guest's 24-hour window is closed.",
        "components": [
            _body("Hi {{1}}, here are the details of {{2}} you asked about: {{3}} Reply here with your dates and group size "
                  "and we'll check availability.",
                  ["Kiran", "Wild Karnataka, 3 nights", "https://rathaa.example/links#pkg-wild-karnataka"]),
        ],
    },
    {
        "name": REENGAGE, "label": "Win back (offer)", "category": "MARKETING",
        "when": "45 days after a lead was lost, only if the guest agreed to offers (P8).",
        "components": [
            _body("Hi {{1}}, planning a getaway soon? {{2}} has new dates open this season. Reply here and we'll share "
                  "what's available.",
                  ["Kiran", "Ratha"]),
            _quick(BTN_SHOW_OPTIONS, BTN_STOP_PROMOS),
        ],
    },
]
# Kept apart from PACK (the playbooks' pack, linted and listed on the Workflows page): the analyst's own template.
ANALYST_PACK: list[dict] = [{
    "name": ANALYST_BRIEF, "label": "Business report", "when": "The analyst's daily / weekly / monthly report to owners and managers.",
    "components": [
        {"type": "HEADER", "format": "DOCUMENT"},
        _body("{{1}} {{2}} is ready: {{3}} Open it for the full report and the changes waiting for you.",
              ["Ratha", "weekly brief", "Leads up, replies slower than last week."]),
        {"type": "BUTTONS", "buttons": [{"type": "URL", "text": "Open report", "url": APP_URL_TOKEN + "/r/analyst/{{1}}",
                                         "example": [APP_URL_TOKEN + "/r/analyst/sample"]}]},
    ],
}]
BY_NAME = {t["name"]: t for t in PACK}


def missed_call_text(first: str, brand: str, when: str) -> str:
    """The same message as plain text, for a guest whose 24-hour window is open."""
    return (f"Hi {first}, sorry we missed your call to {brand}. Reply here with your dates and group size and we'll help "
            f"right away. We'll also call you back {when}.")


def tried_calling_text(first: str, agent: str, brand: str) -> str:
    return (f"Hi {first}, {agent} from {brand} just tried calling you about your enquiry. Maybe you're busy. We can share "
            f"the details and proposal right here on WhatsApp.")


def callback_ack_text(first: str, when: str) -> str:
    return f"Sure {first}, we'll call you {when}."


# Plain-text versions of the follow-ups (24-hour window open, autopilot mode): the same words as the templates.
def quote_followup_text(first: str, trip: str, shared: str) -> str:
    return (f"Hi {first}, just checking you received the proposal for {trip} we shared on {shared}. Happy to answer any "
            f"questions or adjust it for you.")


def quote_final_text(first: str, trip: str, valid: str) -> str:
    return f"Hi {first}, your proposal for {trip} is valid until {valid}. Shall we hold these dates for you?"


def checkin_text(first: str, trip: str) -> str:
    return (f"Hi {first}, following up on your enquiry about {trip}. Are you still planning the trip? Reply with your "
            f"dates and we'll check availability.")


def reengage_text(first: str, brand: str) -> str:
    return f"Hi {first}, planning a getaway soon? {brand} has new dates open this season. Reply here and we'll share what's available."


def _model():
    from app.api.v1.endpoints.messaging import TemplateCategory, TemplateStatus, WATemplate
    return WATemplate, TemplateStatus, TemplateCategory


def pack_out(db: Session, tenant_id: str) -> list[dict]:
    """Each lead-pack template with this workspace's status ("approved", "pending", "draft", ... or None = not created)."""
    WATemplate, _, _ = _model()
    rank = {"approved": 5, "pending": 4, "draft": 3, "submission_failed": 2, "rejected": 1}
    best: dict[str, object] = {}
    for r in db.query(WATemplate).filter(WATemplate.tenant_id == tenant_id, WATemplate.name.in_(list(BY_NAME))).all():
        st = getattr(r.status, "value", r.status)
        cur = best.get(r.name)
        if cur is None or rank.get(st, 0) > rank.get(getattr(cur.status, "value", cur.status), 0):
            best[r.name] = r
    out = []
    for t in PACK:
        row = best.get(t["name"])
        body = next(c["text"] for c in t["components"] if c["type"] == "BODY")
        out.append({"name": t["name"], "label": t["label"], "when": t["when"], "body": body,
                    "buttons": [b["text"] for c in t["components"] if c["type"] == "BUTTONS" for b in c["buttons"]],
                    "template_id": row.id if row else None,
                    "status": getattr(row.status, "value", row.status) if row else None,
                    "rejection_reason": getattr(row, "rejection_reason", None) if row else None})
    return out


def status_of(db: Session, tenant_id: str, name: str) -> Optional[str]:
    return next((t["status"] for t in pack_out(db, tenant_id) if t["name"] == name), None)


def _with_app_url(component: dict) -> dict:
    """A URL button names this deployment's app address (Meta reviews the fixed part of a URL once)."""
    import json
    from app.core.config import settings
    raw = json.dumps(component)
    return json.loads(raw.replace(APP_URL_TOKEN, (settings.FRONTEND_URL or "").rstrip("/"))) if APP_URL_TOKEN in raw else dict(component)


def create_analyst_drafts(db: Session, tenant_id: str, actor_id: Optional[str]) -> dict:
    """Add the analyst's delivery template as a DRAFT (same rules as the lead pack: nothing is submitted to Meta here; the
    DOCUMENT header gets its sample from the template editor's Submit step). Safe to repeat."""
    WATemplate, TemplateStatus, TemplateCategory = _model()
    names = [t["name"] for t in ANALYST_PACK]
    existing = {r.name for r in db.query(WATemplate.name).filter(WATemplate.tenant_id == tenant_id, WATemplate.language == LANGUAGE,
                                                                 WATemplate.name.in_(names)).all()}
    created = []
    for t in ANALYST_PACK:
        if t["name"] in existing:
            continue
        db.add(WATemplate(tenant_id=tenant_id, name=t["name"], language=LANGUAGE, category=TemplateCategory.UTILITY,
                          status=TemplateStatus.DRAFT, components=[_with_app_url(c) for c in t["components"]]))
        created.append(t["name"])
    if created:
        append_audit(db, tenant_id=tenant_id, actor_user_id=actor_id, action="analyst.template_created",
                     target_type="wa_template", target_id=None, payload={"created": created})
    db.commit()
    rows = db.query(WATemplate).filter(WATemplate.tenant_id == tenant_id, WATemplate.name.in_(names)).all()
    return {"created": created, "templates": [{"name": r.name, "status": getattr(r.status, "value", r.status), "template_id": r.id}
                                              for r in rows]}


def create_drafts(db: Session, tenant_id: str, actor_id: Optional[str]) -> dict:
    """Add a DRAFT for each lead-pack template the workspace does not have yet (same name + language). Safe to repeat."""
    WATemplate, TemplateStatus, TemplateCategory = _model()
    existing = {r.name for r in db.query(WATemplate.name).filter(WATemplate.tenant_id == tenant_id, WATemplate.language == LANGUAGE,
                                                                 WATemplate.name.in_(list(BY_NAME))).all()}
    created = []
    for t in PACK:
        if t["name"] in existing:
            continue
        category = TemplateCategory.MARKETING if t.get("category") == "MARKETING" else TemplateCategory.UTILITY
        db.add(WATemplate(tenant_id=tenant_id, name=t["name"], language=LANGUAGE, category=category,
                          status=TemplateStatus.DRAFT, components=[_with_app_url(c) for c in t["components"]]))
        created.append(t["name"])
    if created:
        append_audit(db, tenant_id=tenant_id, actor_user_id=actor_id, action="workflows.lead_pack_created",
                     target_type="wa_template", target_id=None, payload={"created": created})
    db.commit()
    return {"created": created, "templates": pack_out(db, tenant_id)}
