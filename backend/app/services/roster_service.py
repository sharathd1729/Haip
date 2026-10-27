"""Shift roster: who is on duty, and who an alert goes to at each escalation step (docs/ops/OPS_MODULE_PLAN.md §3).

This module is the ONLY place that picks alert recipients. Incidents, balance-due escalations, checklist reminders and shift
digests all call recipients_for_step / first_step_with_recipients; nothing else may choose a person on its own.

Times: shift patterns are stored as local minutes in the tenant's timezone (default Asia/Kolkata); overrides are absolute
timestamps. A pattern whose end is at or before its start crosses midnight and covers the early hours of the next weekday.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy.orm import Session

from app.models.ops import (
    EscalationChain,
    ShiftOverride,
    ShiftPattern,
    StaffDuty,
    StaffProfile,
)
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.ops import DEFAULT_CHAIN

log = structlog.get_logger()

OWNER_FALLBACK = {"type": "role", "role": "owner"}


@dataclass(frozen=True)
class Recipient:
    name: str
    staff_id: str | None = None
    user_id: str | None = None
    phone: str | None = None
    whatsapp_ok: bool = False  # has a number AND (is a HAIP user, or opted in as staff)

    @property
    def key(self) -> str:
        return self.staff_id or self.user_id or self.phone or self.name


@dataclass
class StepResolution:
    step: int
    spec: dict
    recipients: list[Recipient] = field(default_factory=list)


def tenant_tz(db: Session, tenant_id: str) -> ZoneInfo:
    tz_name = db.query(Tenant.timezone).filter_by(id=tenant_id).scalar() or "Asia/Kolkata"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        log.error("tenant_timezone_invalid", tenant_id=tenant_id, timezone=tz_name)
        return ZoneInfo("Asia/Kolkata")


def _aware(at: datetime | None) -> datetime:
    at = at or datetime.now(UTC)
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def pattern_covers(p: ShiftPattern, local: datetime) -> bool:
    minute = local.hour * 60 + local.minute
    wd = local.weekday()
    if p.end_minute > p.start_minute:
        return wd == p.weekday and p.start_minute <= minute < p.end_minute
    # crosses midnight
    return (wd == p.weekday and minute >= p.start_minute) or (wd == (p.weekday + 1) % 7 and minute < p.end_minute)


def _property_match(row_property: str | None, property_id: str | None) -> bool:
    # A tenant-wide row (NULL) covers every property; an item without a property matches any row.
    return row_property is None or property_id is None or row_property == property_id


def _active_overrides(db: Session, tenant_id: str, at: datetime) -> list[ShiftOverride]:
    return (
        db.query(ShiftOverride)
        .filter(
            ShiftOverride.tenant_id == tenant_id,
            ShiftOverride.starts_at <= at,
            ShiftOverride.ends_at > at,
        )
        .all()
    )


def _staff_by_ids(db: Session, tenant_id: str, ids: set[str]) -> dict[str, StaffProfile]:
    if not ids:
        return {}
    rows = (
        db.query(StaffProfile)
        .filter(
            StaffProfile.tenant_id == tenant_id,
            StaffProfile.id.in_(ids),
            StaffProfile.active.is_(True),
        )
        .all()
    )
    return {s.id: s for s in rows}


def _ordered(ids: list[str], staff: dict[str, StaffProfile]) -> list[StaffProfile]:
    seen: set[str] = set()
    out: list[Recipient] = []
    for sid in ids:
        if sid in staff and sid not in seen:
            seen.add(sid)
            out.append(staff[sid])
    return out


def on_shift(
    db: Session,
    tenant_id: str,
    duty: str,
    property_id: str | None = None,
    at: datetime | None = None,
) -> list[StaffProfile]:
    """Active staff on shift for this duty (and property) at this moment, after leave/swap/extra overrides."""
    at = _aware(at)
    local = at.astimezone(tenant_tz(db, tenant_id))
    patterns = (
        db.query(ShiftPattern)
        .filter(
            ShiftPattern.tenant_id == tenant_id,
            ShiftPattern.duty == duty,
            ShiftPattern.active.is_(True),
        )
        .all()
    )
    ids = [p.staff_id for p in patterns if _property_match(p.property_id, property_id) and pattern_covers(p, local)]

    overrides = _active_overrides(db, tenant_id, at)
    off = {o.staff_id for o in overrides if o.kind in ("leave", "swap")}
    for o in overrides:
        if o.kind == "swap" and o.staff_id in ids and o.replacement_staff_id:
            ids.append(o.replacement_staff_id)  # covers the swapped person's shift
        elif (
            o.kind == "extra"
            and _property_match(o.property_id, property_id)
            and (o.duty == duty or (o.duty is None and _holds_duty(db, tenant_id, o.staff_id, duty, property_id)))
        ):
            ids.append(o.staff_id)
    ids = [i for i in ids if i not in off]  # leave always wins, also over an extra shift or a swap cover
    return _ordered(ids, _staff_by_ids(db, tenant_id, set(ids)))


def _holds_duty(db: Session, tenant_id: str, staff_id: str, duty: str, property_id: str | None) -> bool:
    rows = db.query(StaffDuty).filter_by(tenant_id=tenant_id, staff_id=staff_id, duty=duty).all()
    return any(_property_match(r.property_id, property_id) for r in rows)


def duty_holders(
    db: Session,
    tenant_id: str,
    duty: str,
    property_id: str | None = None,
    at: datetime | None = None,
) -> list[StaffProfile]:
    """Everyone holding the duty for the property (on shift or not), minus anyone on leave right now."""
    at = _aware(at)
    rows = db.query(StaffDuty).filter_by(tenant_id=tenant_id, duty=duty).all()
    ids = [r.staff_id for r in rows if _property_match(r.property_id, property_id)]
    off = {o.staff_id for o in _active_overrides(db, tenant_id, at) if o.kind in ("leave", "swap")}
    ids = [i for i in ids if i not in off]
    return _ordered(ids, _staff_by_ids(db, tenant_id, set(ids)))


def chain_for(db: Session, tenant_id: str, duty: str, property_id: str | None) -> list[dict]:
    """Property-specific chain, else the tenant-wide chain for the duty, else the default. Always ends with the owner."""
    q = db.query(EscalationChain).filter(EscalationChain.tenant_id == tenant_id, EscalationChain.duty == duty)
    chain = None
    if property_id:
        chain = q.filter(EscalationChain.property_id == property_id).first()
    if chain is None:
        chain = q.filter(EscalationChain.property_id.is_(None)).first()
    steps = list(chain.steps) if chain and chain.steps else [dict(s) for s in DEFAULT_CHAIN]
    if not any(s.get("type") == "role" and s.get("role") == "owner" for s in steps):
        steps.append(dict(OWNER_FALLBACK))  # never drop an alert: the owner is always the last step
    return steps


def _staff_recipient(s: StaffProfile) -> Recipient:
    return Recipient(
        name=s.name,
        staff_id=s.id,
        user_id=s.user_id,
        phone=s.phone_e164,
        whatsapp_ok=bool(s.phone_e164 and s.whatsapp_opt_in_at),
    )


def _role_recipients(db: Session, tenant_id: str, role: str) -> list[Recipient]:
    from app.services import phone_identity

    users = (
        db.query(User)
        .filter(
            User.tenant_id == tenant_id,
            User.is_active.is_(True),
            User.is_deleted.is_(False),
        )
        .filter(User.role == UserRole(role))
        .all()
    )
    linked = {
        s.user_id: s
        for s in db.query(StaffProfile)
        .filter(
            StaffProfile.tenant_id == tenant_id,
            StaffProfile.active.is_(True),
            StaffProfile.user_id.in_([u.id for u in users] or [""]),
        )
        .all()
    }
    out = []
    for u in users:
        staff = linked.get(u.id)
        if staff:
            out.append(
                Recipient(
                    name=u.name or staff.name,
                    staff_id=staff.id,
                    user_id=u.id,
                    phone=staff.phone_e164,
                    whatsapp_ok=bool(staff.phone_e164),
                )
            )
        else:
            phone = phone_identity.normalize(u.phone) if u.phone else None
            out.append(
                Recipient(
                    name=u.name or u.email,
                    user_id=u.id,
                    phone=phone,
                    whatsapp_ok=bool(phone),
                )
            )
    return out


def recipients_for_spec(
    db: Session,
    tenant_id: str,
    spec: dict,
    duty: str,
    property_id: str | None,
    at: datetime | None = None,
) -> list[Recipient]:
    kind = spec.get("type")
    if kind == "on_shift":
        return [_staff_recipient(s) for s in on_shift(db, tenant_id, spec.get("duty") or duty, property_id, at)]
    if kind == "duty":
        return [_staff_recipient(s) for s in duty_holders(db, tenant_id, spec.get("duty") or duty, property_id, at)]
    if kind == "role" and spec.get("role") in {r.value for r in UserRole}:
        return _role_recipients(db, tenant_id, spec["role"])
    if kind == "staff" and spec.get("staff_id"):
        s = _staff_by_ids(db, tenant_id, {spec["staff_id"]}).get(spec["staff_id"])
        return [_staff_recipient(s)] if s else []
    log.error("ops_chain_step_invalid", tenant_id=tenant_id, spec=spec)
    return []


def _dedupe(recipients: list[Recipient]) -> list[Recipient]:
    seen, out = set(), []
    for r in recipients:
        keys = {k for k in (r.staff_id, r.user_id, r.phone) if k}
        if keys & seen:
            continue
        seen |= keys
        out.append(r)
    return out


def recipients_for_step(
    db: Session,
    tenant_id: str,
    duty: str,
    property_id: str | None,
    step: int,
    severity: str = "normal",
    at: datetime | None = None,
) -> StepResolution:
    steps = chain_for(db, tenant_id, duty, property_id)
    if step >= len(steps):
        return StepResolution(step=step, spec={}, recipients=[])
    spec = steps[step]
    recipients = recipients_for_spec(db, tenant_id, spec, duty, property_id, at)
    if step == 0 and severity == "critical" and duty != "ops_manager":
        # Critical items reach the ops manager on shift at once, not after a step times out.
        recipients += recipients_for_spec(
            db,
            tenant_id,
            {"type": "on_shift", "duty": "ops_manager"},
            duty,
            property_id,
            at,
        )
    return StepResolution(step=step, spec=spec, recipients=_dedupe(recipients))


def chain_length(db: Session, tenant_id: str, duty: str, property_id: str | None) -> int:
    return len(chain_for(db, tenant_id, duty, property_id))


def first_step_with_recipients(
    db: Session,
    tenant_id: str,
    duty: str,
    property_id: str | None,
    start: int,
    severity: str = "normal",
    at: datetime | None = None,
) -> tuple[StepResolution | None, list[int]]:
    """The first step at or after `start` that has anyone to alert, plus the steps skipped because they were empty."""
    skipped: list[int] = []
    for step in range(start, chain_length(db, tenant_id, duty, property_id)):
        res = recipients_for_step(db, tenant_id, duty, property_id, step, severity, at)
        if res.recipients:
            return res, skipped
        skipped.append(step)
    return None, skipped
