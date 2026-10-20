"""Should a playbook WhatsApp go to this guest right now? One function, ``check``, run when the step FIRES (not when it was
scheduled): a lot can change in the 45 seconds after a missed call.

Returns None when the message may go, else a plain reason (shown on the Workflows activity list and in the audit trail).
The checks, cheapest first:
  * the workspace switch or this playbook is off
  * an active old-style automation rule also WhatsApps after a call (it writes no message row, so the caps below cannot see
    its sends: two engines would double-message the guest; the owner turns one off)
  * staff paused playbooks on this lead
  * the guest has no usable WhatsApp number, or the number belongs to a team member
  * the guest said STOP
  * the guest already holds a booking, or the lead is closed (won, lost, unsuitable, marketing)
  * a person contacted the guest after the trigger (they are already in touch)
  * the guest got a playbook WhatsApp in the last few hours (shared cap across the guest-message playbooks)
  * the workspace reached its daily cap
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.lead_workflow import LeadJourney, PlaybookAction
from app.services import lead_playbook_catalog as cat
from app.services import lead_playbook_settings as settings

SENT_STATUSES = ("queued", "done")


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def conflicting_rules(db: Session, tenant_id: str) -> list[str]:
    """Active automation rules that WhatsApp the guest after a call (the old engine). Names, for the Workflows page."""
    from app.models.automation import AutomationRule
    rows = db.query(AutomationRule.name).filter(
        AutomationRule.tenant_id == tenant_id, AutomationRule.is_active.is_(True),
        AutomationRule.trigger == "call_completed",
        AutomationRule.action.in_(("send_whatsapp_template", "send_whatsapp_draft")),
    ).all()
    return [r[0] for r in rows]


def staff_phones(db: Session, tenant_id: str) -> set[str]:
    from app.models.user import User
    from app.services.guest_service import normalize_phone
    out = set()
    for (phone,) in db.query(User.phone).filter(User.tenant_id == tenant_id, User.phone.isnot(None)).all():
        try:
            out.add(normalize_phone(phone))
        except Exception:  # noqa: BLE001 -- an odd profile number must not break the check
            continue
    return out


def phone_problem(db: Session, tenant_id: str, guest) -> Optional[str]:
    from app.services.guest_service import normalize_phone
    from app.workers.tasks.send_whatsapp import _bad_number_reason
    phone = (getattr(guest, "phone", None) or "").strip()
    if not phone or phone.startswith("DELETED_"):
        return "the guest has no phone number"
    if _bad_number_reason(phone):
        return "the guest's number is not a valid WhatsApp number"
    try:
        if normalize_phone(phone) in staff_phones(db, tenant_id):
            return "the number belongs to a team member"
    except Exception:  # noqa: BLE001
        pass
    return None


def lead_closed(db: Session, tenant_id: str, inquiry) -> bool:
    if inquiry is None or not inquiry.stage_id:
        return False
    from app.services.work_queue_service import _done_stage_ids
    return inquiry.stage_id in set(_done_stage_ids(db, tenant_id))


def contacted_since(db: Session, tenant_id: str, guest_id: str, since: datetime) -> bool:
    from app.services.work_queue_signals import touch_rows
    return any(kind == "contact" for _g, _at, kind, _ch in touch_rows(db, tenant_id, {guest_id: since}))


def recent_guest_messages(db: Session, tenant_id: str, guest_id: str, hours: int, now: datetime) -> int:
    return db.query(PlaybookAction.id).filter(
        PlaybookAction.tenant_id == tenant_id, PlaybookAction.guest_id == guest_id,
        PlaybookAction.playbook_key.in_(cat.GUEST_MESSAGE_PLAYBOOKS),
        PlaybookAction.action.in_(("wa_template", "wa_text")), PlaybookAction.status.in_(SENT_STATUSES),
        PlaybookAction.created_at >= now - timedelta(hours=hours),
    ).count()


def sent_today(db: Session, tenant_id: str, now: datetime) -> int:
    return db.query(PlaybookAction.id).filter(
        PlaybookAction.tenant_id == tenant_id, PlaybookAction.action.in_(("wa_template", "wa_text")),
        PlaybookAction.status.in_(SENT_STATUSES), PlaybookAction.created_at >= now - timedelta(hours=24),
    ).count()


def check(db: Session, tenant, guest, inquiry, *, playbook: str, since: datetime,
          now: Optional[datetime] = None, cap_exempt: bool = False) -> Optional[str]:
    """None = the guest message may go now; otherwise why not. ``since`` = when the trigger happened (the call)."""
    now = now or datetime.now(timezone.utc)
    s = settings.get(tenant)
    pb = settings.playbook(tenant, playbook)
    if not pb["active"]:
        return "this playbook is switched off"
    if playbook in (cat.MISSED_INBOUND_CALL, cat.UNANSWERED_OUTBOUND) and conflicting_rules(db, tenant.id):
        return "an older automation rule also messages guests after calls; turn one of them off"
    if guest is None:
        return "no guest on this call"
    if inquiry is not None:
        paused = db.query(LeadJourney.playbooks_paused_at).filter(
            LeadJourney.tenant_id == tenant.id, LeadJourney.inquiry_id == inquiry.id).scalar()
        if paused:
            return "playbooks are paused on this lead"
    problem = phone_problem(db, tenant.id, guest)
    if problem:
        return problem
    from app.services.sales_agent_service import guest_said_stop
    if guest_said_stop(db, tenant.id, guest.id):
        return "the guest asked us to stop messaging them"
    from app.services.work_queue_signals import booked_guests
    from app.core.tenant_tz import get_tenant_now
    if guest.id in booked_guests(db, tenant.id, [guest.id], get_tenant_now(tenant).date()):
        return "the guest already has a booking"
    if lead_closed(db, tenant.id, inquiry):
        return "the lead is closed"
    if contacted_since(db, tenant.id, guest.id, _aware(since)):
        return "someone already contacted the guest after the call"
    if not cap_exempt:
        if recent_guest_messages(db, tenant.id, guest.id, int(s["guest_cap_hours"]), now):
            return f"the guest already got an automatic WhatsApp in the last {s['guest_cap_hours']} h"
        if sent_today(db, tenant.id, now) >= int(s["daily_cap"]):
            return "the workspace reached its daily limit of automatic WhatsApps"
    return None
