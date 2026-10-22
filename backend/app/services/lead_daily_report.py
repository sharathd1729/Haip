"""The daily lead report (CRM reporting, 22 Oct 2026): what each agent did with enquiries on one IST day, and what a PERSON
said about them. GET /reports/daily-validation (endpoints/reports_crm.py). Guest enquiries only (lead_types).

Automatic numbers (computed from records; nobody typed them):
  received      enquiries created that day, by their owner (``assigned_to``; none = Unassigned)
  handled       enquiries a person contacted that day: a message they sent (not an unsent AI draft, not a note) in the
                enquiry's conversation, or a call they placed or answered on it; by that person
  in_valid_stage  of the day's received enquiries, those now in a "valid" pipeline stage and not marked spam
  conversions   bookings made that day (not cancelled) from an enquiry, by the enquiry's owner
Human review (lead_review_service; never written by anything automatic):
  reviewed / valid / not_valid   reviews recorded that day, by the reviewer
  not_yet_reviewed              of the day's received enquiries, those nobody has reviewed yet (as of now)

Per agent rows plus a ``total`` row computed on its own (an enquiry two agents both handled is ONE in the total).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.models.call import Call
from app.models.conversation import Conversation, Message, MessageDirection
from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.models.property import Stay
from app.models.user import User
from app.services import kpi_metrics
from app.services.date_presets import ist_range_to_utc
from app.services.lead_types import is_guest_sql

AUTO_KEYS = ("received", "handled", "in_valid_stage", "conversions")
HUMAN_KEYS = ("reviewed", "valid", "not_valid", "not_yet_reviewed")

DEFINITIONS = {
    "received": "Enquiries created that day, by their owner.",
    "handled": "Enquiries a person contacted that day (a message they sent or a call on the enquiry), by that person.",
    "in_valid_stage": "Of the day's enquiries, those now in a valid pipeline stage (automatic, from the stage).",
    "conversions": "Bookings made that day from an enquiry, by the enquiry's owner.",
    "reviewed": "Enquiries a person marked Valid or Not valid that day, by the reviewer.",
    "valid": "Of those, marked Valid.",
    "not_valid": "Of those, marked Not valid.",
    "not_yet_reviewed": "Of the day's enquiries, those nobody has reviewed yet.",
}


def build(db: Session, tenant_id: str, day: date) -> dict:
    iso = day.isoformat()
    start, end = ist_range_to_utc(iso, iso)[2:]
    per: dict = defaultdict(lambda: {"automatic": {k: set() for k in AUTO_KEYS}, "human": {k: set() for k in HUMAN_KEYS}})
    total = {"automatic": {k: set() for k in AUTO_KEYS}, "human": {k: set() for k in HUMAN_KEYS}}

    def add(agent, block, key, inquiry_id):
        per[agent][block][key].add(inquiry_id)
        total[block][key].add(inquiry_id)

    guest = is_guest_sql(Inquiry.lead_type)
    valid_stages = {s.id for s in db.query(PipelineStage.id).filter(PipelineStage.tenant_id == tenant_id, PipelineStage.category == "valid")}
    for inq in db.query(Inquiry).filter(Inquiry.tenant_id == tenant_id, guest, Inquiry.created_at >= start, Inquiry.created_at <= end):
        add(inq.assigned_to, "automatic", "received", inq.id)
        if inq.stage_id in valid_stages and inq.qualification_status != kpi_metrics.UNQUALIFIED:
            add(inq.assigned_to, "automatic", "in_valid_stage", inq.id)
        if not inq.validation_status:
            add(inq.assigned_to, "human", "not_yet_reviewed", inq.id)

    # A person's messages and calls that day. A chat not tied to an enquiry counts for the guest's newest enquiry.
    sent = (db.query(Message.sender_id, Conversation.inquiry_id, Conversation.guest_id)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .filter(Message.tenant_id == tenant_id, Conversation.tenant_id == tenant_id,
                    Message.direction == MessageDirection.OUTBOUND, Message.sender_id.isnot(None), Message.is_internal.isnot(True),
                    (Message.is_ai_generated.isnot(True)) | (Message.was_approved.is_(True)),
                    Message.created_at >= start, Message.created_at <= end).all())
    called = (db.query(Call.agent_id, Call.inquiry_id, Call.guest_id)
              .filter(Call.tenant_id == tenant_id, Call.agent_id.isnot(None), Call.created_at >= start, Call.created_at <= end).all())
    touches = [*sent, *called]
    loose = {g for _, i, g in touches if not i and g}
    newest = {}
    for inquiry_id, guest_id in (db.query(Inquiry.id, Inquiry.guest_id).filter(Inquiry.tenant_id == tenant_id, Inquiry.guest_id.in_(list(loose)))
                                 .order_by(Inquiry.created_at.asc()).all() if loose else []):
        newest[guest_id] = inquiry_id
    wanted = {i or newest.get(g) for _, i, g in touches} - {None}
    guest_ids = {i for (i,) in db.query(Inquiry.id).filter(Inquiry.tenant_id == tenant_id, Inquiry.id.in_(list(wanted)), guest)} if wanted else set()
    for agent, inquiry_id, guest_id in touches:
        target = inquiry_id or newest.get(guest_id)
        if target in guest_ids:
            add(agent, "automatic", "handled", target)

    for stay_id, owner in (db.query(Stay.id, Inquiry.assigned_to).join(Inquiry, Inquiry.id == Stay.inquiry_id)
                           .filter(Stay.tenant_id == tenant_id, Inquiry.tenant_id == tenant_id, guest,
                                   Stay.status.in_(list(kpi_metrics.OCCUPYING_STATUSES)),
                                   Stay.created_at >= start, Stay.created_at <= end)):
        add(owner, "automatic", "conversions", stay_id)

    for inq in db.query(Inquiry).filter(Inquiry.tenant_id == tenant_id, guest, Inquiry.validated_at >= start,
                                        Inquiry.validated_at <= end, Inquiry.validation_status.isnot(None)):
        add(inq.validated_by, "human", "reviewed", inq.id)
        add(inq.validated_by, "human", "valid" if inq.validation_status == "valid" else "not_valid", inq.id)

    ids = [a for a in per if a]
    names = dict(db.query(User.id, User.name).filter(User.tenant_id == tenant_id, User.id.in_(ids)).all()) if ids else {}

    def counts(block: dict) -> dict:
        return {b: {k: len(v) for k, v in block[b].items()} for b in ("automatic", "human")}

    agents = [{"agent_id": a, "name": names.get(a, "Former teammate") if a else "Unassigned", **counts(per[a])} for a in per]
    agents.sort(key=lambda r: (r["agent_id"] is None, -r["automatic"]["received"], -r["automatic"]["handled"], r["name"]))
    return {"date": iso, "timezone": "Asia/Kolkata", "agents": agents, "total": counts(total), "definitions": DEFINITIONS,
            "lead_types": ["guest"]}


def parse_day(value: Optional[str], today: date) -> date:
    if not value:
        return today
    return date.fromisoformat(value[:10])
