"""Recurring SOPs, tasks and reminders (phase S3). Called by the hourly beat (sops.tick_tenant), never per request.

* Cycles: a weekly / monthly / seasonal checklist opens its next cycle at `next_cycle_at`: fresh progress rows, due dates
  from the step's due_days (inside the period), the old cycle's open tasks closed. Seasonal = 21 days before the next long
  weekend at least 30 days after this cycle opened (marketing_demand), else 90 days on.
* Tasks: a to-do step due within a day gets ONE Task (kind "sop", assigned to the checklist's assignee; it shows on My
  day). Ticking the step closes it; closing it from Tasks ticks a manual step (service.on_task_toggled).
* Reminders, the lead-alert ladder (no new channel): overdue = level 1 to the assignee, 3 days later level 2 to the
  managers (owners if none), each once per step per cycle. Push always; staff WhatsApp only to opted-in people with a
  phone, outside quiet hours, not inside the hold gap, with `haip_staff_sop_due_v1` APPROVED (lead_alert_sender.deliver,
  PlaybookAction playbook_key "sop"). Quiet hours hold the whole round.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta

import structlog
from dateutil.relativedelta import relativedelta
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.sop import SopInstance, SopStepProgress, SopVersion
from app.models.task import Task
from app.models.tenant import Tenant
from app.services.sops.catalogue import BY_KEY, Template

log = structlog.get_logger()

TEMPLATE = "haip_staff_sop_due_v1"  # = wa_lead_pack.SOP_DUE (drafted by POST /sops/templates)
SECOND_LEVEL_AFTER = timedelta(days=3)
TASK_LEAD = timedelta(days=1)
SEASON_LEAD_DAYS, SEASON_MIN_GAP, SEASON_FALLBACK = 21, 30, 90
PERIOD = {"weekly": relativedelta(weeks=1), "monthly": relativedelta(months=1)}


def _aware(d: datetime | None) -> datetime | None:
    from datetime import UTC

    return d.replace(tzinfo=UTC) if d is not None and d.tzinfo is None else d


def next_cycle_at(db: Session, tenant: Tenant, t: Template, opened: datetime) -> datetime | None:
    if t.recurrence in PERIOD:
        return opened + PERIOD[t.recurrence]
    if t.recurrence != "seasonal":
        return None
    from app.core.tenant_tz import get_tz
    from app.services import marketing_demand

    tz = get_tz(tenant)
    start = opened.astimezone(tz).date()
    lws = marketing_demand.long_weekends(
        marketing_demand.home_state(db, tenant), start + timedelta(days=SEASON_MIN_GAP), start + timedelta(days=180)
    )
    if not lws:
        return opened + timedelta(days=SEASON_FALLBACK)
    day = datetime.fromisoformat(lws[0]["start"]).date() - timedelta(days=SEASON_LEAD_DAYS)
    return datetime.combine(day, time(9, 0), tzinfo=tz)


def due_at(t: Template, days: int, opened: datetime) -> datetime:
    if t.recurrence in PERIOD:  # inside the period, so a weekly step is never due after the next week opens
        days = min(days, ((opened + PERIOD[t.recurrence]) - opened).days - 1)
    return opened + timedelta(days=max(days, 0))


def _close_task(db: Session, task_id: str | None, now: datetime) -> None:
    task = db.query(Task).filter_by(id=task_id).first() if task_id else None
    if task is not None and not task.is_done:
        task.is_done, task.completed_at = True, now


def open_cycles(db: Session, tenant: Tenant, now: datetime) -> int:
    rows = (
        db.query(SopInstance)
        .filter(
            SopInstance.tenant_id == tenant.id,
            SopInstance.status.in_(("active", "done")),
            SopInstance.next_cycle_at.isnot(None),
            SopInstance.next_cycle_at <= now,
        )
        .all()
    )
    for inst in rows:
        t = BY_KEY[inst.template_key]
        for p in db.query(SopStepProgress).filter_by(tenant_id=tenant.id, instance_id=inst.id, cycle_no=inst.cycle_no):
            _close_task(db, p.task_id, now)
        inst.cycle_no += 1
        extra = [e["key"] for e in (inst.overrides or {}).get("extra_steps") or []]
        for key, days in [(s.key, s.due_days) for s in t.steps] + [(k, 7) for k in extra]:
            db.add(
                SopStepProgress(
                    tenant_id=tenant.id,
                    instance_id=inst.id,
                    cycle_no=inst.cycle_no,
                    step_key=key,
                    due_at=due_at(t, days, now),
                )
            )
        inst.status, inst.next_cycle_at = "active", next_cycle_at(db, tenant, t, now)
        append_audit(
            db,
            tenant_id=tenant.id,
            action="sop.cycle_opened",
            actor_user_id=None,
            target_type="sop_instance",
            target_id=inst.id,
            payload={"template": inst.template_key, "cycle": inst.cycle_no, "actor": "system"},
        )
    db.flush()
    return len(rows)


def _open_steps(db: Session, inst: SopInstance) -> list[tuple[dict, SopStepProgress]]:
    """(step, progress) for this cycle's to-do, visible steps of an active checklist."""
    from app.services.sops import service

    prog = {
        p.step_key: p
        for p in db.query(SopStepProgress).filter_by(
            tenant_id=inst.tenant_id, instance_id=inst.id, cycle_no=inst.cycle_no
        )
    }
    return [
        (s, prog[s["key"]])
        for s in service._steps(db, inst)
        if not s["hidden"] and s["status"] == "todo" and s["key"] in prog
    ]


def make_tasks(db: Session, tenant: Tenant, now: datetime) -> int:
    n = 0
    for inst in db.query(SopInstance).filter_by(tenant_id=tenant.id, status="active").all():
        if inst.current_version_id is None:
            continue
        t = BY_KEY[inst.template_key]
        for s, p in _open_steps(db, inst):
            if p.task_id or not p.due_at or _aware(p.due_at) > now + TASK_LEAD:
                continue
            task = Task(
                tenant_id=tenant.id,
                title=f"Get found: {s['title']} ({t.title.split(':')[0]})"[:255],
                due_date=p.due_at,
                priority="medium",
                assigned_to=inst.assignee_id,
                kind="sop",
            )
            db.add(task)
            db.flush()
            p.task_id = task.id
            n += 1
    db.flush()  # autoflush is off: on_task_toggled and the next tick look tasks up by task_id
    return n


def _deliver(db: Session, tenant: Tenant, user, lines: list[str], now: datetime) -> str:
    """Push always; staff WhatsApp when allowed. Returns how it went, for the audit."""
    from app.models.lead_workflow import PlaybookAction
    from app.services import lead_alert_sender, lead_alert_service
    from app.services.push_service import send_to_tenant

    title = f"{len(lines)} Get found step(s) overdue"
    send_to_tenant(
        db, tenant.id, title, "; ".join(lines)[:180], url="/dashboard/marketing/sops", tag="sop-due", user_id=user.id
    )
    phone = lead_alert_service.staff_phone(user)
    if phone is None:
        return "push"
    hold = lead_alert_service.wa_hold(db, tenant, user.id, now)
    if hold or lead_alert_sender.template_approved(db, tenant.id, TEMPLATE) is None:
        return "push"
    action = PlaybookAction(
        tenant_id=tenant.id,
        playbook_key="sop",
        action="staff_wa",
        status="queued",
        recipient_user_id=user.id,
        template_name=TEMPLATE,
        payload={"title": title, "body": "; ".join(lines)[:500], "url": "/dashboard/marketing/sops"},
    )
    db.add(action)
    db.flush()
    first = (user.name or "there").split(" ")[0]
    ok = lead_alert_sender.deliver(db, action, phone, [first, str(len(lines)), lines[0][:60]], with_buttons=False)
    return "push+whatsapp" if ok else "push"


def remind(db: Session, tenant: Tenant, now: datetime) -> int:
    from app.models.user import User
    from app.services import lead_alert_service

    if lead_alert_service.in_quiet_hours(tenant, now):
        return 0
    by_user: dict[str, list[str]] = defaultdict(list)
    touched: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for inst in db.query(SopInstance).filter_by(tenant_id=tenant.id, status="active").all():
        t = BY_KEY[inst.template_key]
        for s, p in _open_steps(db, inst):
            due = _aware(p.due_at)
            if due is None or due > now:
                continue
            level = (
                2 if p.reminder_level >= 1 and due <= now - SECOND_LEVEL_AFTER else 1 if p.reminder_level == 0 else 0
            )
            if not level:
                continue
            for u in lead_alert_service.recipients_for(db, tenant.id, level, inst.assignee_id):
                by_user[u.id].append(f"{s['title']} ({t.title.split(':')[0]})")
            p.reminder_level = level
            touched[inst.id].append((s["key"], level))
    users = {u.id: u for u in db.query(User).filter(User.id.in_(list(by_user)))} if by_user else {}
    sent = {uid: _deliver(db, tenant, users[uid], lines, now) for uid, lines in by_user.items() if uid in users}
    for inst_id, steps in touched.items():
        append_audit(
            db,
            tenant_id=tenant.id,
            action="sop.reminder_sent",
            actor_user_id=None,
            target_type="sop_instance",
            target_id=inst_id,
            payload={
                "steps": [{"step": k, "level": lv} for k, lv in steps],
                "delivery": sorted(set(sent.values())),
                "actor": "system",
            },
        )
    db.flush()
    return len(sent)


def tick(db: Session, tenant: Tenant, now: datetime) -> dict:
    return {
        "cycles": open_cycles(db, tenant, now),
        "tasks": make_tasks(db, tenant, now),
        "reminded": remind(db, tenant, now),
    }


# ── Nightly refresh: a new version only when what the steps were made from changed ──────────────────────────────────

MAX_REFRESH = 20


def stale_reason(db: Session, tenant: Tenant, inst: SopInstance) -> str | None:
    from app.services.sops import generate, rules

    v = db.get(SopVersion, inst.current_version_id) if inst.current_version_id else None
    if v is None or inst.generating:
        return None
    t = BY_KEY[inst.template_key]
    if v.template_version != t.version:
        return "template_updated"
    if v.rules_digest != rules.digest():
        return "catalogue_updated"
    if v.inputs_sha != generate.inputs_sha(generate.collect(db, tenant, inst)):
        return "data_changed"
    return None


def refresh(db: Session, tenant: Tenant) -> list[tuple[str, str]]:
    """(instance id, reason) to regenerate; marks them queued. The caller queues sops.generate_version after commit."""
    out = []
    for inst in (
        db.query(SopInstance)
        .filter(SopInstance.tenant_id == tenant.id, SopInstance.status.in_(("active", "done")))
        .limit(200)
    ):
        if len(out) >= MAX_REFRESH:
            break
        reason = stale_reason(db, tenant, inst)
        if reason:
            inst.generating = "queued"
            out.append((inst.id, reason))
    db.flush()
    return out
