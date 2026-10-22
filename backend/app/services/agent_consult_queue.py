"""Open consults as ``consult`` items of the ONE work queue (work_queue_service; highest priority, above a missed call).

A consult is an explicit "the AI is waiting for you" about a guest, so it is listed whether or not we hold their phone number
(unlike the other person kinds). ``since`` is when the team's clock started (the consult's SLA start: now inside business
hours, the next opening time outside them), so the shared severity rule (SLA_MINUTES["consult"]) never marks a 23:00 question
"late" before the team is back. Agents see consults they own or nobody owns; owners/managers see all.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.agent_consult import AgentConsult
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.services import agent_consult_settings as settings_svc
from app.services import agent_escalation_rules as rules


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def items(db: Session, tenant_id: str, scope_user_id: Optional[str], now: datetime) -> list:
    from app.services.work_queue_service import QueueItem, _names
    q = db.query(AgentConsult).filter(AgentConsult.tenant_id == tenant_id, AgentConsult.status == "open")
    if scope_user_id:
        q = q.filter(or_(AgentConsult.assigned_to == scope_user_id, AgentConsult.assigned_to.is_(None)))
    rows = q.order_by(AgentConsult.sla_due_at.asc()).limit(200).all()
    if not rows:
        return []
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    guests = {g.id: g for g in db.query(Guest).filter(Guest.tenant_id == tenant_id,
                                                      Guest.id.in_([r.guest_id for r in rows if r.guest_id])).all()}
    owners = _names(db, tenant_id, {r.assigned_to for r in rows if r.assigned_to})
    out = []
    for c in rows:
        g = guests.get(c.guest_id)
        labels = rules.labels(c.reason_codes)
        created = _aware(c.created_at)
        start = created if tenant is None or settings_svc.in_business_hours(tenant, created) else settings_svc.next_opening(tenant, created)
        out.append(QueueItem(
            kind="consult",
            title=(g.name if g and g.name else None) or "Guest",
            detail=f"“{(c.question or '')[:140]}”",
            action="Answer",
            href=f"/dashboard/inbox?conversation={c.conversation_id}&consult={c.id}",
            inquiry_id=c.inquiry_id,
            guest_id=c.guest_id,
            guest_phone=g.phone if g else None,
            owner_id=c.assigned_to,
            owner_name=owners.get(c.assigned_to),
            channels=[c.channel] if c.channel else [],
            since=start,
            has_draft=bool(c.proposed_answer),
            facts=[lab["label"] for lab in labels[:3]],
        ))
    return out
