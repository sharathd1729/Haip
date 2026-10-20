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

# Quick-reply button texts. The webhook matches a tap on these (lead_playbook_engine.on_guest_button).
BTN_CALL_ME_BACK = "Call me back"
BTN_CALL_ME_LATER = "Call me later"
BTN_SHARE_HERE = "Share details here"


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
]
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


def create_drafts(db: Session, tenant_id: str, actor_id: Optional[str]) -> dict:
    """Add a DRAFT for each lead-pack template the workspace does not have yet (same name + language). Safe to repeat."""
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
        append_audit(db, tenant_id=tenant_id, actor_user_id=actor_id, action="workflows.lead_pack_created",
                     target_type="wa_template", target_id=None, payload={"created": created})
    db.commit()
    return {"created": created, "templates": pack_out(db, tenant_id)}
