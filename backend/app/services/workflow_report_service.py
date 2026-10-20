"""Lead workflows report (Workflows page, Report tab): how fast leads were handled and where they dropped off.

Cohort: enquiries RECEIVED in the period (``lead_journeys.received_at``, IST days, from/to inclusive). Every number comes
from lead_journeys (milestones written once by lead_journey_tracker) plus three source tables for what the journey does
not hold: calls (missed calls returned), playbook_actions (automatic WhatsApps and whether the guest answered) and tasks
(follow-ups done). Metric definitions: docs/analytics/KPI_METRIC_CATALOGUE.md, section "Lead workflows".

  funnel        received -> seen -> called -> first contact -> proposal -> followed up -> sold, each the number of leads in
                the cohort that reached the step (a later step can be higher than an earlier one: a lead can get a proposal
                without being called, so each bar is "how many", not "how many of the previous")
  agents        one row per owner (inquiries.assigned_to; "Unassigned" for none): leads, median minutes from received to
                seen / first call / first contact / proposal, missed calls returned, sold, the top lost reason
  missed calls  inbound calls missed in the period that a later answered call returned (calls.recovered_by_call_id)
  auto replies  playbook WhatsApps to guests in the period after which the guest wrote back within 24 hours
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from statistics import median
from typing import Optional

from sqlalchemy.orm import Session

from app.models.call import Call, CallDirection
from app.models.conversation import Conversation, Message, MessageDirection
from app.models.inquiry import Inquiry
from app.models.lead_workflow import LeadJourney, PlaybookAction
from app.models.task import Task
from app.models.user import User
from app.services.date_presets import IST

FUNNEL = (("received", "Received"), ("seen", "Seen"), ("called", "Called"), ("contacted", "First contact"),
          ("proposal", "Proposal sent"), ("followed_up", "Followed up"), ("sold", "Sold"))
SPEEDS = (("seen", "first_viewed_at"), ("first_call", "first_call_attempt_at"), ("first_contact", "first_human_contact_at"),
          ("proposal", "proposal_shared_at"))


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _bounds(d_from: date, d_to: date) -> tuple[datetime, datetime]:
    return (datetime.combine(d_from, time.min, tzinfo=IST).astimezone(timezone.utc),
            datetime.combine(d_to + timedelta(days=1), time.min, tzinfo=IST).astimezone(timezone.utc))


def _minutes(start: Optional[datetime], end: Optional[datetime]) -> Optional[float]:
    if start is None or end is None:
        return None
    return max(0.0, (_aware(end) - _aware(start)).total_seconds() / 60)


def _median(values: list[float]) -> Optional[int]:
    return round(median(values)) if values else None


def report(db: Session, tenant_id: str, d_from: date, d_to: date, agent_id: Optional[str] = None) -> dict:
    lo, hi = _bounds(d_from, d_to)
    rows = (db.query(LeadJourney, Inquiry.assigned_to)
            .join(Inquiry, Inquiry.id == LeadJourney.inquiry_id)
            .filter(LeadJourney.tenant_id == tenant_id, Inquiry.tenant_id == tenant_id,
                    LeadJourney.received_at >= lo, LeadJourney.received_at < hi).all())
    inquiry_ids = [j.inquiry_id for j, _ in rows]
    followed = _followed_up(db, tenant_id, inquiry_ids)

    def reached(j: LeadJourney) -> dict[str, bool]:
        return {"received": True, "seen": j.first_viewed_at is not None, "called": j.first_call_attempt_at is not None,
                "contacted": j.first_human_contact_at is not None, "proposal": j.proposal_shared_at is not None,
                "followed_up": j.inquiry_id in followed, "sold": j.outcome == "won"}

    by_agent: dict[Optional[str], list[LeadJourney]] = {}
    for j, owner in rows:
        by_agent.setdefault(owner, []).append(j)
    cohort = [j for j, owner in rows if agent_id is None or owner == agent_id]

    funnel = [{"key": k, "label": label, "count": sum(1 for j in cohort if reached(j)[k])} for k, label in FUNNEL]
    missed = _missed_calls(db, tenant_id, lo, hi, agent_id)
    names = dict(db.query(User.id, User.name).filter(User.tenant_id == tenant_id,
                                                     User.id.in_([a for a in by_agent if a])).all()) if by_agent else {}
    agents = []
    for owner, js in by_agent.items():
        speeds = {key: _median([m for m in (_minutes(j.received_at, getattr(j, col)) for j in js) if m is not None])
                  for key, col in SPEEDS}
        lost = [j.lost_reason for j in js if j.outcome == "lost" and j.lost_reason]
        agent_missed = _missed_calls(db, tenant_id, lo, hi, owner or "__none__")
        agents.append({
            "agent_id": owner, "name": names.get(owner, "Unassigned") if owner else "Unassigned", "leads": len(js),
            **{f"{k}_minutes": v for k, v in speeds.items()},
            "missed_calls": agent_missed["missed"], "missed_calls_returned": agent_missed["returned"],
            "sold": sum(1 for j in js if j.outcome == "won"), "lost": sum(1 for j in js if j.outcome == "lost"),
            "top_lost_reason": max(set(lost), key=lost.count) if lost else None,
        })
    agents.sort(key=lambda a: (a["agent_id"] is None, -a["leads"]))

    lost_reasons: dict[str, int] = {}
    for j in cohort:
        if j.outcome == "lost":
            key = j.lost_reason or "not_recorded"
            lost_reasons[key] = lost_reasons.get(key, 0) + 1
    contact_minutes = [m for m in (_minutes(j.received_at, j.first_human_contact_at) for j in cohort) if m is not None]
    autos = _auto_replies(db, tenant_id, lo, hi, [j.inquiry_id for j in cohort] if agent_id else None)
    drops = [{"from": FUNNEL[i - 1][1], "to": label, "lost": funnel[i - 1]["count"] - funnel[i]["count"]}
             for i, (_k, label) in enumerate(FUNNEL) if i > 0 and funnel[i - 1]["count"] > funnel[i]["count"]]
    return {
        "from": d_from.isoformat(), "to": d_to.isoformat(), "agent_id": agent_id,
        "summary": {
            "leads": len(cohort),
            "median_first_contact_minutes": _median(contact_minutes),
            "missed_calls": missed["missed"], "missed_calls_returned": missed["returned"],
            "auto_messages": autos["sent"], "auto_messages_replied": autos["replied"],
            "sold": sum(1 for j in cohort if j.outcome == "won"),
        },
        "funnel": funnel,
        "biggest_drop": max(drops, key=lambda d: d["lost"]) if drops else None,
        "agents": agents,
        "lost_reasons": sorted(({"reason": k, "count": v} for k, v in lost_reasons.items()), key=lambda r: -r["count"]),
    }


def _followed_up(db: Session, tenant_id: str, inquiry_ids: list[str]) -> set[str]:
    """Leads with a follow-up after the first contact: a playbook follow-up step that fired, or a follow-up/call task done."""
    if not inquiry_ids:
        return set()
    from app.services import lead_playbook_catalog as cat
    out = {i for (i,) in db.query(PlaybookAction.inquiry_id).filter(
        PlaybookAction.tenant_id == tenant_id, PlaybookAction.inquiry_id.in_(inquiry_ids),
        PlaybookAction.playbook_key.in_(cat.FOLLOWUP_PLAYBOOKS), PlaybookAction.status.in_(("queued", "done"))).all()}
    out |= {i for (i,) in db.query(Task.inquiry_id).filter(
        Task.tenant_id == tenant_id, Task.inquiry_id.in_(inquiry_ids), Task.is_done.is_(True),
        Task.kind.in_(("followup", "call"))).all()}
    return out


def _missed_calls(db: Session, tenant_id: str, lo: datetime, hi: datetime, agent_id: Optional[str]) -> dict:
    """Inbound calls missed in the period, and how many a later answered call returned. ``agent_id`` narrows to calls about
    that person's leads ("__none__" = leads nobody owns)."""
    from app.services.call_status_service import is_missed_call
    q = db.query(Call).filter(Call.tenant_id == tenant_id, Call.direction == CallDirection.INBOUND,
                              Call.created_at >= lo, Call.created_at < hi)
    if agent_id is not None:
        q = q.outerjoin(Inquiry, Inquiry.id == Call.inquiry_id)
        q = q.filter(Inquiry.assigned_to.is_(None)) if agent_id == "__none__" else q.filter(Inquiry.assigned_to == agent_id)
    calls = [c for c in q.all() if is_missed_call(c)]
    return {"missed": len(calls), "returned": sum(1 for c in calls if c.recovered_by_call_id)}


def _auto_replies(db: Session, tenant_id: str, lo: datetime, hi: datetime, inquiry_ids: Optional[list[str]]) -> dict:
    """Playbook WhatsApps to guests sent in the period, and how many got a guest reply within 24 hours."""
    q = db.query(PlaybookAction).filter(PlaybookAction.tenant_id == tenant_id,
                                        PlaybookAction.action.in_(("wa_template", "wa_text")),
                                        PlaybookAction.status.in_(("queued", "done")),
                                        PlaybookAction.created_at >= lo, PlaybookAction.created_at < hi)
    if inquiry_ids is not None:
        q = q.filter(PlaybookAction.inquiry_id.in_(inquiry_ids or ["-"]))
    sent = q.all()
    replied = 0
    for a in sent:
        if not a.guest_id:
            continue
        at = _aware(a.created_at)
        if db.query(Message.id).join(Conversation, Conversation.id == Message.conversation_id).filter(
                Conversation.tenant_id == tenant_id, Conversation.guest_id == a.guest_id,
                Message.direction == MessageDirection.INBOUND, Message.created_at > at,
                Message.created_at <= at + timedelta(hours=24)).first():
            replied += 1
    return {"sent": len(sent), "replied": replied}
