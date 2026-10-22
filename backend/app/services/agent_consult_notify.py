"""Who hears about a consult, and the escalation ladder when nobody answers.

  notify(level)   push (per person) + SSE ``consult_opened`` / ``consult_escalated`` + a staff WhatsApp alert through the
                  existing team-alert sender (lead_alert_sender, template haip_staff_lead_alert_v1 / _escalation_v1) ONLY to
                  people who opted in (users.whatsapp_alerts_opt_in_at + a phone), never during the team's quiet hours
  escalate        beat ``agent_consults.escalate_all_tenants`` every 2 minutes: an open consult past ``sla_due_at`` climbs
                  agent -> manager -> owner (a new SLA each step); after the owner's SLA it is EXPIRED and a high-priority
                  callback task is raised. A consult already answered in the Inbox is closed instead (resolve_elsewhere).

Recipients reuse lead_alert_service.recipients_for (level 1 = the lead's owner, 2 = managers, 3 = owners). Every step is audited.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.agent_consult import AgentConsult
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.services import agent_consult_settings as settings_svc
from app.services import agent_escalation_rules as rules

log = structlog.get_logger()

LEVEL_NUMBER = {"agent": 1, "manager": 2, "owner": 3}
NEXT_LEVEL = {"agent": "manager", "manager": "owner"}
LEVEL_TITLE = {"agent": "Question for you", "manager": "Manager needed", "owner": "Owner needed"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def href(consult: AgentConsult) -> str:
    return f"/dashboard/inbox?conversation={consult.conversation_id}&consult={consult.id}"


def _who(db: Session, consult: AgentConsult) -> str:
    name = db.query(Guest.name).filter_by(id=consult.guest_id, tenant_id=consult.tenant_id).scalar() if consult.guest_id else None
    return ((name or "A guest").strip().split(" ")[0]) or "A guest"


def emit_sse(tenant_id: str, event: str, consult: AgentConsult) -> None:
    try:
        import json

        import redis

        from app.core.config import settings
        r = redis.from_url(settings.REDIS_URL)
        r.publish(f"sse:{tenant_id}", json.dumps({"event": event, "conversation_id": consult.conversation_id,
                                                   "consult_id": consult.id}))
    except Exception as exc:  # noqa: BLE001 -- live updates are best-effort; the queue and push still carry it
        log.warning("consult_sse_failed", error=str(exc)[:200])


def notify(db: Session, tenant: Tenant, consult: AgentConsult, *, escalated: bool = False) -> dict:
    """Tell this level's people. Push always; WhatsApp only to opted-in staff outside quiet hours. Flushes; caller commits."""
    from app.services import lead_alert_sender as sender
    from app.services import lead_alert_service as alerts
    from app.services import wa_lead_pack as pack
    from app.models.lead_workflow import PlaybookAction
    level = consult.level or "manager"
    people = alerts.recipients_for(db, tenant.id, LEVEL_NUMBER.get(level, 2), consult.assigned_to if level == "agent" else None)
    who = _who(db, consult)
    why = ", ".join(r["label"] for r in rules.labels(consult.reason_codes)[:2]) or "Needs a person"
    title = f"{LEVEL_TITLE.get(level, 'Manager needed')}: {who}"
    body = f"{why}. “{(consult.question or '')[:90]}”"[:180]
    pushed = whatsapped = 0
    quiet = alerts.in_quiet_hours(tenant)
    for user in people:
        alerts._push(db, tenant.id, user.id, title, body, href(consult))
        pushed += 1
        phone = None if quiet else alerts.staff_phone(user)
        if not phone:
            continue
        action = PlaybookAction(tenant_id=tenant.id, run_id=None, playbook_key="consult", inquiry_id=consult.inquiry_id,
                                guest_id=consult.guest_id, recipient_user_id=user.id, action="staff_wa", status="queued",
                                template_name=pack.STAFF_ESCALATION if escalated else pack.STAFF_ALERT,
                                payload={"title": title, "body": body, "url": href(consult), "consult_id": consult.id})
        db.add(action)
        db.flush()
        values = [LEVEL_TITLE.get(level, "Manager needed"), f"{who}, a question", why, waited(consult), "you"]
        if sender.deliver(db, action, phone, values):
            whatsapped += 1
        else:
            alerts.push_fallback(db, action)
    emit_sse(tenant.id, "consult_escalated" if escalated else "consult_opened", consult)
    log.info("consult_notified", tenant_id=tenant.id, consult_id=consult.id, consult_level=level, pushed=pushed, whatsapped=whatsapped)
    return {"pushed": pushed, "whatsapped": whatsapped}


def waited(consult: AgentConsult, now: Optional[datetime] = None) -> str:
    minutes = max(0, int(((now or _now()) - _aware(consult.created_at)).total_seconds() // 60))
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60} min"


def _expire(db: Session, tenant: Tenant, consult: AgentConsult, now: datetime) -> None:
    from app.services.agent_consult_service import _task
    who = _who(db, consult)
    task = _task(db, consult, f"Call back: unanswered question — {who}", consult.assigned_to)
    consult.status, consult.answer_mode, consult.answered_at, consult.task_id = "expired", "expired", now, task.id
    append_audit(db, tenant_id=tenant.id, action="agent_consult.expired", target_type="agent_consult", target_id=consult.id,
                 payload={"actor": "system", "task_id": task.id, "level": consult.level})
    alerts_push_owner(db, tenant, consult, task.title)


def alerts_push_owner(db: Session, tenant: Tenant, consult: AgentConsult, title: str) -> None:
    from app.services import lead_alert_service as alerts
    for user in alerts.recipients_for(db, tenant.id, 3, None):
        alerts._push(db, tenant.id, user.id, "Question expired", title, href(consult))


def escalate(db: Session, tenant: Tenant, now: Optional[datetime] = None) -> dict:
    """One pass over this tenant's open consults past their SLA. Commits once at the end."""
    from app.services.agent_consult_service import resolve_elsewhere
    now = now or _now()
    out = {"escalated": 0, "expired": 0, "resolved": 0}
    rows = (db.query(AgentConsult).filter(AgentConsult.tenant_id == tenant.id, AgentConsult.status == "open",
                                          AgentConsult.sla_due_at <= now).order_by(AgentConsult.sla_due_at).limit(100).all())
    minutes = int(settings_svc.get(tenant)["sla_minutes"])
    for c in rows:
        if resolve_elsewhere(db, c):
            out["resolved"] += 1
            continue
        nxt = NEXT_LEVEL.get(c.level)
        if nxt is None:
            _expire(db, tenant, c, now)
            out["expired"] += 1
            continue
        before = c.level
        c.level, c.escalated_at = nxt, now
        c.sla_due_at = now + timedelta(minutes=minutes) if settings_svc.in_business_hours(tenant, now) \
            else settings_svc.sla_due(tenant, now)
        append_audit(db, tenant_id=tenant.id, action="agent_consult.escalated", target_type="agent_consult", target_id=c.id,
                     payload={"actor": "system", "from": before, "to": nxt})
        db.flush()
        notify(db, tenant, c, escalated=True)
        out["escalated"] += 1
    db.commit()
    return out
