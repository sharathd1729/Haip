"""Escalation engine for ops items (docs/ops/OPS_MODULE_PLAN.md §4).

Lifecycle: open → (alert step 0) → acknowledged → resolved, or cancelled. While open and not acknowledged, each step has the
severity's ack window; when it runs out the item moves to the next step of the chain (roster_service.chain_for). After the last
step it re-alerts that step up to MAX_REPEATS times, then marks the item escalation_exhausted (it stays open and visible).
Acknowledging starts the resolve clock; a resolve breach alerts managers and the owner once.

Never silent: an empty step is logged as a roster gap and skipped, an undeliverable step escalates at once, and the owner is
always the chain's last step. This module only writes rows (items, events, queued sends); ops_alert_sender delivers them, from
Celery, so request handlers never wait on Meta. Functions return the ids of sends to deliver; the caller commits, then queues them.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.models.ops import OpsAlertSend, OpsEscalationEvent, OpsItem, OpsSettings, StaffProfile
from app.schemas.ops import DEFAULT_QUIET_HOURS, DEFAULT_SLA_MINUTES, DEFAULT_TEMPLATES
from app.services import roster_service

log = structlog.get_logger()

MAX_REPEATS = 3
DELIVERABLE = ("queued", "sent", "delivered", "read")
RESOLVE_BREACH_STEP = -1          # sends for a resolve-deadline breach (not part of the ack chain)
STALE_QUEUED = timedelta(minutes=2)


def _now(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# ── Settings ───────────────────────────────────────────────────────────────

def get_settings_row(db: Session, tenant_id: str) -> Optional[OpsSettings]:
    return db.query(OpsSettings).filter_by(tenant_id=tenant_id).first()


def effective_settings(db: Session, tenant_id: str) -> dict:
    row = get_settings_row(db, tenant_id)
    sla = {k: tuple(v) for k, v in DEFAULT_SLA_MINUTES.items()}
    for sev, pair in ((row.sla or {}) if row else {}).items():
        if sev in sla and isinstance(pair, (list, tuple)) and len(pair) == 2:
            sla[sev] = (int(pair[0]), int(pair[1]))
    return {
        "alerts_enabled": row.alerts_enabled if row else True,
        "sla": sla,
        "quiet_hours": (row.quiet_hours if row and row.quiet_hours else dict(DEFAULT_QUIET_HOURS)),
        "templates": {**DEFAULT_TEMPLATES, **((row.templates or {}) if row else {})},
        "template_language": (row.template_language if row else None) or "en",
    }


def _minute(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def quiet_until(db: Session, tenant_id: str, now: datetime, quiet: dict) -> Optional[datetime]:
    """If `now` falls in quiet hours, the moment they end (UTC); else None."""
    tz = roster_service.tenant_tz(db, tenant_id)
    local = now.astimezone(tz)
    start, end = _minute(quiet["start"]), _minute(quiet["end"])
    if start == end:
        return None
    minute = local.hour * 60 + local.minute
    inside = (start <= minute < end) if start < end else (minute >= start or minute < end)
    if not inside:
        return None
    end_local = local.replace(hour=end // 60 % 24, minute=end % 60, second=0, microsecond=0)
    if end_local <= local:
        end_local += timedelta(days=1)
    return end_local.astimezone(timezone.utc)


# ── Events ─────────────────────────────────────────────────────────────────

def _event(db: Session, item: OpsItem, event: str, now: datetime, step: Optional[int] = None,
           staff_id: Optional[str] = None, user_id: Optional[str] = None, detail: Optional[dict] = None) -> None:
    db.add(OpsEscalationEvent(tenant_id=item.tenant_id, item_id=item.id, event=event, step=step,
                              actor_staff_id=staff_id, actor_user_id=user_id, detail=detail, created_at=now))


# ── Create ─────────────────────────────────────────────────────────────────

def create_item(db: Session, tenant_id: str, *, title: str, severity: str, duty: str, kind: str = "incident",
                summary: Optional[str] = None, category: Optional[str] = None, property_id: Optional[str] = None,
                stay_id: Optional[str] = None, guest_id: Optional[str] = None, conversation_id: Optional[str] = None,
                service_request_id: Optional[str] = None, source: str = "staff", created_by: Optional[str] = None,
                now: Optional[datetime] = None) -> tuple[OpsItem, list[str]]:
    now = _now(now)
    cfg = effective_settings(db, tenant_id)
    _, resolve_minutes = cfg["sla"][severity]
    item = OpsItem(
        tenant_id=tenant_id, kind=kind, title=title, summary=summary, category=category, severity=severity, duty=duty,
        status="open", source=source, property_id=property_id, stay_id=stay_id, guest_id=guest_id,
        conversation_id=conversation_id, service_request_id=service_request_id, created_by=created_by,
        resolve_due_at=now + timedelta(minutes=resolve_minutes), current_step=0,
    )
    db.add(item)
    db.flush()
    held = quiet_until(db, tenant_id, now, cfg["quiet_hours"]) if severity in ("low", "normal") else None
    _event(db, item, "created", now, user_id=created_by,
           detail={"severity": severity, "duty": duty, "source": source, **({"held_until": held.isoformat()} if held else {})})
    if held:
        item.dispatch_after = held
        item.resolve_due_at = held + timedelta(minutes=resolve_minutes)
        db.flush()
        return item, []
    return item, start_step(db, item, 0, now)


# ── Dispatch / escalate ────────────────────────────────────────────────────

def start_step(db: Session, item: OpsItem, start: int, now: Optional[datetime] = None, repeat: bool = False) -> list[str]:
    """Alert the first step at or after `start` that has anyone in it. Returns queued send ids."""
    now = _now(now)
    cfg = effective_settings(db, item.tenant_id)
    res, skipped = roster_service.first_step_with_recipients(
        db, item.tenant_id, item.duty, item.property_id, start, item.severity, now)
    for s in skipped:
        log.error("ops_roster_gap", tenant_id=item.tenant_id, item_id=item.id, step=s, duty=item.duty)
        _event(db, item, "roster_gap", now, step=s)
    if res is None:
        log.error("ops_escalation_no_recipients", tenant_id=item.tenant_id, item_id=item.id)
        item.escalation_exhausted = True
        item.ack_due_at = None
        _event(db, item, "exhausted", now, detail={"reason": "no recipients in any remaining step"})
        db.flush()
        return []

    ack_minutes, _ = cfg["sla"][item.severity]
    item.current_step = res.step
    item.dispatched_step = res.step
    item.dispatch_after = None
    item.step_started_at = now
    item.ack_due_at = now + timedelta(minutes=ack_minutes)
    template = cfg["templates"]["escalation" if (res.step > 0 or repeat) else "alert"]

    queued = _queue_sends(db, item, res.step, res.recipients, template, cfg["alerts_enabled"])
    _event(db, item, "repeated" if repeat else ("escalated" if res.step > 0 else "alerted"), now, step=res.step,
           detail={"recipients": [r.name for r in res.recipients], "spec": res.spec})
    db.flush()
    if not queued:
        _event(db, item, "undeliverable", now, step=res.step,
               detail={"reason": "nobody in this step can be reached on WhatsApp or push"})
        db.flush()
        return escalate(db, item, now)
    return queued


def _queue_sends(db: Session, item: OpsItem, step: int, recipients, template: str, whatsapp_enabled: bool) -> list[str]:
    queued: list[str] = []
    for r in recipients:
        rows = []
        if whatsapp_enabled and r.whatsapp_ok and r.phone:
            rows.append(OpsAlertSend(tenant_id=item.tenant_id, item_id=item.id, step=step, staff_id=r.staff_id,
                                     user_id=r.user_id, phone_e164=r.phone, channel="whatsapp", template=template,
                                     nonce=secrets.token_urlsafe(8)))
        if r.user_id:
            rows.append(OpsAlertSend(tenant_id=item.tenant_id, item_id=item.id, step=step, staff_id=r.staff_id,
                                     user_id=r.user_id, channel="push", nonce=secrets.token_urlsafe(8)))
        if not rows:
            reason = "WhatsApp alerts are off" if not whatsapp_enabled else "no WhatsApp opt-in or number, and no HAIP login"
            rows.append(OpsAlertSend(tenant_id=item.tenant_id, item_id=item.id, step=step, staff_id=r.staff_id,
                                     phone_e164=r.phone, channel="whatsapp", template=template, status="skipped",
                                     error=reason))
        for row in rows:
            db.add(row)
            db.flush()
            if row.status == "queued":
                queued.append(row.id)
    return queued


def escalate(db: Session, item: OpsItem, now: Optional[datetime] = None) -> list[str]:
    now = _now(now)
    if item.status != "open":
        return []
    nxt = item.current_step + 1
    if nxt < roster_service.chain_length(db, item.tenant_id, item.duty, item.property_id):
        return start_step(db, item, nxt, now)
    if item.repeat_count < MAX_REPEATS:
        item.repeat_count += 1
        return start_step(db, item, item.current_step, now, repeat=True)
    item.escalation_exhausted = True
    item.ack_due_at = None
    log.error("ops_escalation_exhausted", tenant_id=item.tenant_id, item_id=item.id)
    _event(db, item, "exhausted", now, step=item.current_step, detail={"reason": "chain and repeats used up"})
    db.flush()
    return []


# ── Responses ──────────────────────────────────────────────────────────────

def acknowledge(db: Session, item: OpsItem, *, staff_id: Optional[str] = None, user_id: Optional[str] = None,
                via: str = "app", now: Optional[datetime] = None) -> bool:
    now = _now(now)
    if item.status != "open":
        return False
    _, resolve_minutes = effective_settings(db, item.tenant_id)["sla"][item.severity]
    item.status = "acknowledged"
    item.acknowledged_at = now
    item.acknowledged_by_staff_id = staff_id
    item.acknowledged_by_user_id = user_id
    item.ack_due_at = None
    item.resolve_due_at = now + timedelta(minutes=resolve_minutes)
    _event(db, item, "acknowledged", now, step=item.current_step, staff_id=staff_id, user_id=user_id, detail={"via": via})
    db.flush()
    return True


def decline(db: Session, item: OpsItem, send: OpsAlertSend, now: Optional[datetime] = None) -> list[str]:
    """"Can't take it". When everyone alerted in the current step has declined, escalate at once."""
    now = _now(now)
    send.response = "decline"
    _event(db, item, "declined", now, step=send.step, staff_id=send.staff_id, user_id=send.user_id)
    db.flush()
    if item.status != "open" or send.step != item.current_step:
        return []
    step_sends = db.query(OpsAlertSend).filter_by(tenant_id=item.tenant_id, item_id=item.id, step=item.current_step).all()
    people = {s.staff_id or s.user_id or s.phone_e164 for s in step_sends if s.status != "skipped"}
    declined = {s.staff_id or s.user_id or s.phone_e164 for s in step_sends if s.response == "decline"}
    if people and people <= declined:
        return escalate(db, item, now)
    return []


def resolve(db: Session, item: OpsItem, *, staff_id: Optional[str] = None, user_id: Optional[str] = None,
            note: Optional[str] = None, now: Optional[datetime] = None) -> bool:
    now = _now(now)
    if item.status in ("resolved", "cancelled"):
        return False
    if item.status == "open":
        item.acknowledged_at = item.acknowledged_at or now
        item.acknowledged_by_staff_id = item.acknowledged_by_staff_id or staff_id
        item.acknowledged_by_user_id = item.acknowledged_by_user_id or user_id
    item.status = "resolved"
    item.resolved_at = now
    item.resolved_by_staff_id = staff_id
    item.resolved_by_user_id = user_id
    item.resolution_note = note
    item.ack_due_at = None
    _event(db, item, "resolved", now, staff_id=staff_id, user_id=user_id, detail={"note": note} if note else None)
    db.flush()
    return True


def cancel(db: Session, item: OpsItem, *, user_id: str, note: Optional[str] = None,
           now: Optional[datetime] = None) -> bool:
    now = _now(now)
    if item.status in ("resolved", "cancelled"):
        return False
    item.status = "cancelled"
    item.ack_due_at = None
    item.resolution_note = note
    _event(db, item, "cancelled", now, user_id=user_id, detail={"note": note} if note else None)
    db.flush()
    return True


# ── Staff replies on WhatsApp ──────────────────────────────────────────────

def button_payload(send: OpsAlertSend, action: str) -> str:
    return f"ops:{action}:{send.id}:{send.nonce}"


def handle_staff_inbound(db: Session, tenant_id: str, staff: StaffProfile, *, payload: Optional[str] = None,
                         text: Optional[str] = None, now: Optional[datetime] = None) -> list[str]:
    """A message from a staff number: a button tap acknowledges/declines; anything else is logged on their latest item."""
    now = _now(now)
    if payload and payload.startswith("ops:"):
        parts = payload.split(":")
        if len(parts) != 4 or parts[1] not in ("ack", "decline"):
            log.warning("ops_button_payload_malformed", tenant_id=tenant_id, staff_id=staff.id)
            return []
        _, action, send_id, nonce = parts
        send = db.query(OpsAlertSend).filter_by(id=send_id, tenant_id=tenant_id).first()
        if send is None or not send.nonce or not secrets.compare_digest(send.nonce, nonce) or send.staff_id != staff.id:
            log.warning("ops_button_payload_rejected", tenant_id=tenant_id, staff_id=staff.id, send_id=send_id)
            return []
        item = db.query(OpsItem).filter_by(id=send.item_id, tenant_id=tenant_id).first()
        if item is None:
            return []
        if action == "ack":
            send.response = "ack"
            if not acknowledge(db, item, staff_id=staff.id, user_id=staff.user_id, via="whatsapp", now=now):
                _event(db, item, "late_ack", now, step=send.step, staff_id=staff.id,
                       detail={"status_at_tap": item.status})
            return []
        return decline(db, item, send, now)

    latest = (
        db.query(OpsAlertSend)
        .join(OpsItem, OpsItem.id == OpsAlertSend.item_id)
        .filter(OpsAlertSend.tenant_id == tenant_id, OpsAlertSend.staff_id == staff.id,
                OpsItem.status.in_(("open", "acknowledged")))
        .order_by(OpsAlertSend.created_at.desc())
        .first()
    )
    if latest is None:
        log.info("ops_staff_message_no_item", tenant_id=tenant_id, staff_id=staff.id)
        return []
    item = db.query(OpsItem).filter_by(id=latest.item_id, tenant_id=tenant_id).first()
    _event(db, item, "staff_message", now, staff_id=staff.id, detail={"text": (text or "")[:500]})
    db.flush()
    return []


# ── Delivery outcomes ──────────────────────────────────────────────────────

def on_send_failed(db: Session, send: OpsAlertSend, now: Optional[datetime] = None) -> list[str]:
    """A WhatsApp alert that could not be delivered: push the same person if they have a login, and escalate at once when
    nobody in the current step can still be reached. Never leave an undelivered alert waiting out its ack window."""
    now = _now(now)
    item = db.query(OpsItem).filter_by(id=send.item_id, tenant_id=send.tenant_id).first()
    if item is None:
        return []
    _event(db, item, "delivery_failed", now, step=send.step, staff_id=send.staff_id, user_id=send.user_id,
           detail={"channel": send.channel, "error": (send.error or "")[:300]})
    db.flush()
    if item.status != "open" or send.step != item.current_step:
        return []
    alive = (
        db.query(OpsAlertSend.id)
        .filter(OpsAlertSend.tenant_id == item.tenant_id, OpsAlertSend.item_id == item.id,
                OpsAlertSend.step == item.current_step, OpsAlertSend.status.in_(DELIVERABLE))
        .first()
    )
    if alive is None:
        _event(db, item, "undeliverable", now, step=item.current_step)
        db.flush()
        return escalate(db, item, now)
    return []


# ── Periodic tick ──────────────────────────────────────────────────────────

def tick(db: Session, tenant_id: str, now: Optional[datetime] = None, limit: int = 200) -> list[str]:
    """Dispatch held items, escalate overdue acks, flag resolve breaches, re-offer stale queued sends."""
    now = _now(now)
    out: list[str] = []
    held = (db.query(OpsItem).filter(OpsItem.tenant_id == tenant_id, OpsItem.status == "open",
                                     OpsItem.dispatched_step.is_(None), OpsItem.dispatch_after.isnot(None))
            .limit(limit).all())
    for item in held:
        if _aware(item.dispatch_after) <= now:
            out += start_step(db, item, 0, now)

    overdue = (db.query(OpsItem).filter(OpsItem.tenant_id == tenant_id, OpsItem.status == "open",
                                        OpsItem.escalation_exhausted.is_(False), OpsItem.ack_due_at.isnot(None))
               .limit(limit).all())
    for item in overdue:
        if _aware(item.ack_due_at) <= now:
            out += escalate(db, item, now)

    breached = (db.query(OpsItem).filter(OpsItem.tenant_id == tenant_id, OpsItem.status == "acknowledged",
                                         OpsItem.resolve_breached_at.is_(None), OpsItem.resolve_due_at.isnot(None))
                .limit(limit).all())
    for item in breached:
        if _aware(item.resolve_due_at) <= now:
            out += _resolve_breach(db, item, now)

    cutoff = now - STALE_QUEUED
    stale = (db.query(OpsAlertSend).filter(OpsAlertSend.tenant_id == tenant_id, OpsAlertSend.status == "queued")
             .limit(limit).all())
    out += [s.id for s in stale if _aware(s.created_at) <= cutoff and s.id not in out]
    db.flush()
    return out


def _resolve_breach(db: Session, item: OpsItem, now: datetime) -> list[str]:
    cfg = effective_settings(db, item.tenant_id)
    recipients = []
    for role in ("manager", "owner"):
        recipients += roster_service.recipients_for_spec(db, item.tenant_id, {"type": "role", "role": role},
                                                         item.duty, item.property_id, now)
    recipients += roster_service.recipients_for_spec(db, item.tenant_id, {"type": "on_shift", "duty": "ops_manager"},
                                                     item.duty, item.property_id, now)
    item.resolve_breached_at = now
    queued = _queue_sends(db, item, RESOLVE_BREACH_STEP, roster_service._dedupe(recipients),
                          cfg["templates"]["escalation"], cfg["alerts_enabled"])
    log.warning("ops_resolve_breached", tenant_id=item.tenant_id, item_id=item.id)
    _event(db, item, "resolve_breached", now, detail={"recipients": [r.name for r in recipients]})
    db.flush()
    return queued
