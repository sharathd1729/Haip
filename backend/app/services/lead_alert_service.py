"""Team alerts: a lead that waits too long climbs a ladder of people until someone acts (playbooks P3 and P4).

Where "waiting too long" comes from: ONLY work_queue_service.build() -- the same items, the same SLA_MINUTES severities that
My day shows. Nothing here counts leads by itself.

  P3 new_lead_alert   queue kind new_lead          late (15 min) / urgent (1 h) / critical (4 h)
  P4 sla_escalation   queue kinds reply, callback  late (30 min) / urgent (2 h) / critical (8 h)

One playbook_runs row per queue item (trigger_ref "{kind}:{guest}:{waiting since}", status "watching"); ``step`` is the
highest level already alerted, so each level fires ONCE per item:
  late      the lead's owner (the managers when nobody owns it)       WhatsApp "haip_staff_lead_alert_v1" + push
  urgent    the managers (the owners when there are none)            WhatsApp "haip_staff_escalation_v1" + push
  critical  the owners                                                WhatsApp "haip_staff_escalation_v1" + push
When the item leaves the queue (someone replied, called, booked ...) the run closes as "done". It also closes when it goes
cold (stale): that is the morning report's business, not an alarm's.

WhatsApp goes only to a person who opted in (users.whatsapp_alerts_opt_in_at) and has a phone on their profile; everyone
else, and every failed send, gets the push. During quiet hours (default 22:00-08:00 local) alerts are HELD; the first tick
after quiet hours sends each person one morning summary instead of a burst. Acknowledge (a button on the WhatsApp, or the
app) records that the person saw it; it does not stop the ladder -- only acting on the lead does.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import structlog
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.inquiry import Inquiry
from app.models.lead_workflow import PlaybookAction, PlaybookRun
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import lead_alert_sender as sender
from app.services import lead_playbook_catalog as cat
from app.services import lead_playbook_settings as settings
from app.services import wa_lead_pack as pack

log = structlog.get_logger()

LEVELS = {"late": 1, "urgent": 2, "critical": 3}
LEVEL_LABEL = {1: "Late", 2: "Urgent", 3: "Critical"}
KIND_LABEL = {"new_lead": "new lead", "reply": "waiting for a reply", "callback": "missed call to return"}
WATCHING = "watching"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def waited(since: Optional[datetime], now: datetime) -> str:
    if since is None:
        return "a while"
    minutes = max(0, int((now - _aware(since)).total_seconds() // 60))
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} h {rest} min" if rest else f"{hours} h"
    return f"{hours // 24} days" if hours >= 48 else "1 day"


def in_quiet_hours(tenant: Tenant, now: Optional[datetime] = None) -> bool:
    from app.core.tenant_tz import get_tz
    s = settings.get(tenant)
    start, end = int(s["quiet_start_hour"]), int(s["quiet_end_hour"])
    if start == end:
        return False
    hour = (now or _now()).astimezone(get_tz(tenant)).hour
    return (start <= hour or hour < end) if start > end else (start <= hour < end)


def _people(db: Session, tenant_id: str, roles: Iterable[UserRole]) -> list[User]:
    return (db.query(User).filter(User.tenant_id == tenant_id, User.is_active.is_(True), User.is_deleted.isnot(True),
                                  User.role.in_(list(roles))).order_by(User.name).all())


def recipients_for(db: Session, tenant_id: str, level: int, owner_id: Optional[str]) -> list[User]:
    if level == 1 and owner_id:
        owner = db.query(User).filter_by(id=owner_id, tenant_id=tenant_id, is_active=True).first()
        if owner is not None:
            return [owner]
    if level <= 2:
        return _people(db, tenant_id, [UserRole.MANAGER]) or _people(db, tenant_id, [UserRole.OWNER])
    return _people(db, tenant_id, [UserRole.OWNER])


def staff_phone(user: User) -> Optional[str]:
    """The person's own number in E.164 when they agreed to WhatsApp alerts, else None (they get push only)."""
    if not user.whatsapp_alerts_opt_in_at or not user.phone:
        return None
    from app.services.guest_service import normalize_phone
    try:
        return normalize_phone(user.phone)
    except Exception:  # noqa: BLE001 -- a malformed profile number means push only
        return None


def _push(db: Session, tenant_id: str, user_id: str, title: str, body: str, url: str) -> None:
    try:
        from app.services.push_service import send_to_tenant
        send_to_tenant(db, tenant_id, title=title, body=body, url=url, tag="haip-lead-alert", user_id=user_id)
    except Exception as exc:  # noqa: BLE001 -- push is best-effort
        log.warning("lead_alert_push_failed", tenant_id=tenant_id, error=str(exc)[:200])


def push_fallback(db: Session, action: PlaybookAction) -> None:
    """The WhatsApp to this person failed: push them instead (once)."""
    p = action.payload or {}
    if p.get("fallback_pushed") or not action.recipient_user_id:
        return
    _push(db, action.tenant_id, action.recipient_user_id, p.get("title") or "Lead waiting", p.get("body") or "", p.get("url") or "/dashboard/my-day")
    action.payload = {**p, "fallback_pushed": True}
    db.flush()


# ── The ladder ──────────────────────────────────────────────────────────────

def _texts(item: dict, level: int, now: datetime) -> tuple[str, list[str], str, str]:
    """(template, its values, push title, push body). No guest phone number anywhere."""
    first = (item.get("title") or "A guest").strip().split(" ")[0] or "A guest"
    who = f"{first}, {KIND_LABEL.get(item['kind'], 'lead')}"
    facts = ", ".join(item.get("facts") or []) or (item.get("detail") or "No trip details yet")
    since = datetime.fromisoformat(item["since"]) if item.get("since") else None
    wait = waited(since, now)
    owner = item.get("owner_name") or "nobody yet"
    template = pack.STAFF_ALERT if level == 1 else pack.STAFF_ESCALATION
    title = f"{LEVEL_LABEL[level]}: {who}"
    body = f"Waiting {wait}. {facts}"[:180]
    return template, [LEVEL_LABEL[level], who, facts, wait, owner], title, body


def _fire(db: Session, tenant: Tenant, run: PlaybookRun, item: dict, level: int, now: datetime, quiet: bool) -> int:
    template, values, title, body = _texts(item, level, now)
    url = f"/dashboard/leads/{item['inquiry_id']}" if item.get("inquiry_id") else "/dashboard/my-day"
    staff_wa = bool(settings.get(tenant)["staff_whatsapp"])
    sent = 0
    for user in recipients_for(db, tenant.id, level, item.get("owner_id")):
        base = dict(tenant_id=tenant.id, run_id=run.id, playbook_key=run.playbook_key, inquiry_id=item.get("inquiry_id"),
                    guest_id=item.get("guest_id"), recipient_user_id=user.id)
        meta = {"level": level, "kind": item["kind"], "title": title, "body": body, "url": url, "values": values}
        phone = staff_phone(user) if staff_wa else None
        if quiet:
            db.add(PlaybookAction(**base, action="staff_wa" if phone else "push", status="held", template_name=template,
                                  reason="quiet hours: in the morning summary", payload=meta))
            continue
        _push(db, tenant.id, user.id, title, body, url)
        db.add(PlaybookAction(**base, action="push", status="done", payload=meta))
        if phone:
            action = PlaybookAction(**base, action="staff_wa", status="queued", template_name=template, payload=meta)
            db.add(action)
            db.flush()
            sender.deliver(db, action, phone, values)
        sent += 1
    run.step = level
    db.commit()
    return sent


def tick(db: Session, tenant: Tenant, now: Optional[datetime] = None) -> dict:
    """One pass for one workspace: alert new levels, close handled items, send the morning summary. Commits."""
    from app.services import work_queue_service

    now = now or _now()
    active = {key: kinds for key, kinds in cat.ALERT_PLAYBOOKS.items() if settings.playbook(tenant, key)["active"]}
    if not active:
        return {"status": "off"}
    quiet = in_quiet_hours(tenant, now)
    items = work_queue_service.build(db, tenant, None)["items"]
    kind_to_key = {kind: key for key, kinds in active.items() for kind in kinds}
    seen: set[tuple[str, str]] = set()
    fired = 0
    for item in items:
        key = kind_to_key.get(item["kind"])
        level = LEVELS.get(item.get("severity") or "")
        if key is None or not item.get("guest_id") or not item.get("since"):
            continue
        ref = f"{item['kind']}:{item['guest_id']}:{item['since']}"[:120]
        seen.add((key, ref))
        run = db.query(PlaybookRun).filter_by(tenant_id=tenant.id, playbook_key=key, trigger_ref=ref).first()
        if item.get("severity") == "stale":
            if run is not None and run.status == WATCHING:
                run.status, run.stop_reason = "done", "went cold; in the daily report"
            continue
        if level is None:
            continue
        if run is None:
            run = PlaybookRun(tenant_id=tenant.id, playbook_key=key, trigger_ref=ref, inquiry_id=item.get("inquiry_id"),
                              guest_id=item.get("guest_id"), status=WATCHING, step=0, context={"kind": item["kind"]})
            db.add(run)
            db.flush()
        if run.status != WATCHING or level <= run.step:
            continue
        fired += _fire(db, tenant, run, item, level, now, quiet)
    closed = 0
    for run in db.query(PlaybookRun).filter(PlaybookRun.tenant_id == tenant.id, PlaybookRun.status == WATCHING,
                                            PlaybookRun.playbook_key.in_(list(cat.ALERT_PLAYBOOKS))).all():
        if (run.playbook_key, run.trigger_ref) not in seen:
            run.status, run.stop_reason, closed = "done", "handled: the lead left My day", closed + 1
    db.commit()
    digests = 0 if quiet else morning_summary(db, tenant, items, now)
    return {"status": "ok", "fired": fired, "closed": closed, "digests": digests, "quiet": quiet}


def morning_summary(db: Session, tenant: Tenant, items: list[dict], now: datetime) -> int:
    """After quiet hours: one message per person who had alerts held overnight, about what is STILL waiting."""
    held = db.query(PlaybookAction).filter(PlaybookAction.tenant_id == tenant.id, PlaybookAction.status == "held").all()
    if not held:
        return 0
    waiting = [i for i in items if i.get("severity") in LEVELS and i["kind"] in KIND_LABEL]
    oldest = min(waiting, key=lambda i: i.get("since") or "", default=None)
    by_user: dict[str, list[PlaybookAction]] = {}
    for a in held:
        by_user.setdefault(a.recipient_user_id, []).append(a)
    sent = 0
    for user_id, rows in by_user.items():
        for a in rows:
            a.status, a.reason = "done", "sent in the morning summary" if waiting else "handled before morning"
        user = db.query(User).filter_by(id=user_id, tenant_id=tenant.id).first()
        if user is None or not waiting:
            continue
        first = ((oldest.get("title") or "A guest").split(" ") or ["A guest"])[0]
        since = datetime.fromisoformat(oldest["since"]) if oldest.get("since") else None
        values = [str(len(waiting)), first, waited(since, now)]
        _push(db, tenant.id, user.id, f"{len(waiting)} leads waiting", f"Oldest: {first}, waiting {values[2]}.", "/dashboard/my-day")
        phone = staff_phone(user) if settings.get(tenant)["staff_whatsapp"] else None
        if phone:
            action = PlaybookAction(tenant_id=tenant.id, playbook_key=rows[0].playbook_key, recipient_user_id=user.id,
                                    action="staff_wa", status="queued", template_name=pack.STAFF_DIGEST,
                                    payload={"digest": True, "values": values})
            db.add(action)
            db.flush()
            sender.deliver(db, action, phone, values, with_buttons=False)
        sent += 1
    db.commit()
    return sent


# ── P7: tell the owner at once ──────────────────────────────────────────────

def notify_now(db: Session, tenant: Tenant, run: PlaybookRun, inquiry: Optional[Inquiry], title: str, values: list[str]) -> bool:
    """A guest asked for a call back: WhatsApp the lead's owner (managers when nobody owns it) now, outside quiet hours.
    Uses the team alert template, so it only goes once that is approved. True when a WhatsApp went out."""
    if in_quiet_hours(tenant) or not settings.get(tenant)["staff_whatsapp"]:
        return False
    out = False
    for user in recipients_for(db, tenant.id, 1, getattr(inquiry, "assigned_to", None)):
        phone = staff_phone(user)
        if not phone:
            continue
        action = PlaybookAction(tenant_id=tenant.id, run_id=run.id, playbook_key=run.playbook_key, inquiry_id=run.inquiry_id,
                                guest_id=run.guest_id, recipient_user_id=user.id, action="staff_wa", status="queued",
                                template_name=pack.STAFF_ALERT, payload={"title": title, "values": values})
        db.add(action)
        db.flush()
        out = sender.deliver(db, action, phone, values) or out
    db.commit()
    return out


# ── Staff replies: Acknowledge / I'll take it ───────────────────────────────

def acknowledge(db: Session, action: PlaybookAction, user: User, via: str) -> None:
    if action.acked_at is None:
        action.acked_at = _now()
        append_audit(db, tenant_id=action.tenant_id, actor_user_id=user.id, action="workflows.alert_acknowledged",
                     target_type="playbook_action", target_id=action.id, payload={"via": via, "inquiry_id": action.inquiry_id})


def take(db: Session, action: PlaybookAction, user: User, via: str) -> Optional[Inquiry]:
    """The person claims the lead: they become its owner (an audited reassignment)."""
    acknowledge(db, action, user, via)
    if not action.inquiry_id:
        return None
    inquiry = db.query(Inquiry).filter_by(id=action.inquiry_id, tenant_id=action.tenant_id).first()
    if inquiry is None:
        return None
    previous = inquiry.assigned_to
    if previous != user.id:
        from app.services.lead_assignment_service import _set_owner
        _set_owner(db, inquiry, user.id, "claimed", notify=False)
        append_audit(db, tenant_id=action.tenant_id, actor_user_id=user.id, action="workflows.lead_claimed",
                     target_type="inquiry", target_id=inquiry.id, payload={"from": previous, "via": via})
    return inquiry


def staff_by_phone(db: Session, tenant_id: str, phone_e164: str) -> Optional[User]:
    """The opted-in team member whose profile number is this one (their messages to the business number are not leads)."""
    from app.services.guest_service import normalize_phone
    for user in db.query(User).filter(User.tenant_id == tenant_id, User.is_active.is_(True),
                                      User.whatsapp_alerts_opt_in_at.isnot(None), User.phone.isnot(None)).all():
        try:
            if normalize_phone(user.phone) == phone_e164:
                return user
        except Exception:  # noqa: BLE001
            continue
    return None


def handle_staff_inbound(db: Session, tenant_id: str, from_phone: str, payload: Optional[str]) -> str:
    """A WhatsApp from a team member's number. Returns what happened: acked | taken | ignored | wrong_person | unknown."""
    parsed = sender.parse_payload(payload)
    if parsed is None:
        return "ignored"
    action_id, verb = parsed
    action = db.query(PlaybookAction).filter_by(id=action_id, tenant_id=tenant_id).first()
    if action is None or not action.recipient_user_id:
        return "unknown"
    user = db.query(User).filter_by(id=action.recipient_user_id, tenant_id=tenant_id).first()
    if user is None or staff_phone(user) != from_phone:
        log.warning("lead_alert_tap_from_other_number", tenant_id=tenant_id, action_id=action_id)
        return "wrong_person"
    if verb == "take":
        inquiry = take(db, action, user, via="whatsapp")
        db.commit()
        name = ""
        if inquiry is not None and inquiry.guest:
            name = (inquiry.guest.name or "").split(" ")[0]
        sender.send_text(db, tenant_id, from_phone, f"Done: {name or 'the lead'} is now yours in HAIP.")
        return "taken"
    acknowledge(db, action, user, via="whatsapp")
    db.commit()
    sender.send_text(db, tenant_id, from_phone, "Noted. The lead stays in My day until someone acts on it.")
    return "acked"


def recipients_view(db: Session, tenant_id: str) -> list[dict]:
    """Who the ladder can reach and how: the Workflows page shows who still needs a phone or the WhatsApp opt-in."""
    out = []
    for u in _people(db, tenant_id, [UserRole.OWNER, UserRole.MANAGER, UserRole.RESERVATIONS, UserRole.CONCIERGE, UserRole.FOH]):
        out.append({"id": u.id, "name": u.name, "role": getattr(u.role, "value", u.role), "has_phone": bool(u.phone),
                    "whatsapp_opt_in": bool(u.whatsapp_alerts_opt_in_at),
                    "channel": "whatsapp" if staff_phone(u) else "push"})
    return out


def set_opt_in(db: Session, user: User, enabled: bool) -> dict:
    """The person agrees (or stops agreeing) to lead alerts on their own WhatsApp. Self-service, audited."""
    if enabled and not user.phone:
        raise ValueError("Add your phone number to your profile first.")
    before = bool(user.whatsapp_alerts_opt_in_at)
    if enabled != before:
        user.whatsapp_alerts_opt_in_at = _now() if enabled else None
        append_audit(db, tenant_id=user.tenant_id, actor_user_id=user.id,
                     action="workflows.whatsapp_alerts_opted_in" if enabled else "workflows.whatsapp_alerts_opted_out",
                     target_type="user", target_id=user.id, payload={})
    return {"whatsapp_opt_in": bool(user.whatsapp_alerts_opt_in_at), "has_phone": bool(user.phone)}
