"""Lifecycle and lookup of structured business records (docs/ai/RATHA_KB_EVOLUTION.md).

    draft --validate--> published (immutable) --a newer version publishes--> superseded
      |                      |--deactivate--> inactive           rollback = a NEW draft copied from an older version
      `--reject--> rejected

Rules this module enforces and the rest of the product relies on:
  * Guest-facing code reads ONLY through get_effective()/list_effective(): status `published` and an effective window that contains the
    date. A draft, a rejected or inactive version, or a version whose window has not started is never returned.
  * A published version is never modified. Publishing creates the next state of the world; history and rollback follow from that.
  * Every state change writes the audit chain (actor, versions, field-level diff) and is decided by a guarded UPDATE, so two
    simultaneous requests cannot both win.
  * The caller commits.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.business_record import BusinessRecord
from app.schemas.business_data import (
    KIND_MODELS, KINDS, REQUIRES_CONFIRMATION, SINGLETON_KEY, SINGLETON_KINDS, canonical, validate_data,
)

log = structlog.get_logger()


class BusinessDataError(Exception):
    """A refusal with a stable `code` and plain-language `problems` (the API turns it into 404/409/422)."""

    def __init__(self, code: str, message: str, problems: Optional[list[str]] = None, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.problems, self.status = code, message, problems or [], status


def tenant_today(db: Session, tenant_id: str) -> date:
    """Today's date in the tenant's own time zone (Ratha: India). Effective dates are calendar dates the business means, so they
    must not flip at 05:30 local time just because UTC midnight passed."""
    from app.core.tenant_tz import get_tenant_now
    from app.models.tenant import Tenant
    tenant = db.query(Tenant).filter_by(id=tenant_id).first()
    return get_tenant_now(tenant).date() if tenant else datetime.now(timezone.utc).date()


def normalise_key(kind: str, key: Optional[str]) -> str:
    if kind not in KINDS:
        raise BusinessDataError("unknown_kind", f"Unknown kind '{kind}'.", status=422)
    if kind in SINGLETON_KINDS:
        return SINGLETON_KEY
    k = (key or "").strip().lower()
    if not k:
        raise BusinessDataError("key_required", "A key is required for this kind.", status=422)
    return k


def _get(db: Session, tenant_id: str, record_id: str) -> BusinessRecord:
    rec = db.query(BusinessRecord).filter_by(id=record_id, tenant_id=tenant_id).first()
    if rec is None:
        raise BusinessDataError("not_found", "Record not found.", status=404)
    return rec


def parse(rec: BusinessRecord):
    """The validated typed model of a stored record (exact values as Decimal / date)."""
    model, problems = validate_data(rec.kind, rec.data)
    if model is None:
        raise BusinessDataError("corrupt_record", f"Stored data no longer matches its schema: {problems}", problems, status=500)
    return model


def diff_data(old: Any, new: Any, path: str = "") -> list[dict]:
    """Field-level changes between two JSON values: [{path, old, new}]."""
    if isinstance(old, dict) and isinstance(new, dict):
        out: list[dict] = []
        for k in sorted(set(old) | set(new)):
            out += diff_data(old.get(k), new.get(k), f"{path}.{k}" if path else k)
        return out
    if isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        out = []
        for i, (a, b) in enumerate(zip(old, new)):
            out += diff_data(a, b, f"{path}[{i}]")
        return out
    return [] if old == new else [{"path": path or "(record)", "old": old, "new": new}]


# ─── reading (the ONLY way guest-facing code gets business data) ──────────────────────────────────────────

def get_effective(db: Session, tenant_id: str, kind: str, key: str, at: Optional[date] = None) -> Optional[BusinessRecord]:
    at = at or tenant_today(db, tenant_id)
    return (
        db.query(BusinessRecord)
        .filter(
            BusinessRecord.tenant_id == tenant_id, BusinessRecord.kind == kind, BusinessRecord.key == key,
            BusinessRecord.status == "published",
            BusinessRecord.effective_from <= at,
            (BusinessRecord.effective_to.is_(None)) | (BusinessRecord.effective_to >= at),
        )
        .order_by(BusinessRecord.effective_from.desc(), BusinessRecord.version.desc())
        .first()
    )


def list_effective(db: Session, tenant_id: str, kind: str, at: Optional[date] = None) -> list[BusinessRecord]:
    at = at or tenant_today(db, tenant_id)
    rows = (
        db.query(BusinessRecord)
        .filter(
            BusinessRecord.tenant_id == tenant_id, BusinessRecord.kind == kind, BusinessRecord.status == "published",
            BusinessRecord.effective_from <= at,
            (BusinessRecord.effective_to.is_(None)) | (BusinessRecord.effective_to >= at),
        )
        .order_by(BusinessRecord.key, BusinessRecord.effective_from.desc(), BusinessRecord.version.desc())
        .all()
    )
    seen, out = set(), []
    for r in rows:                                   # one per key: the latest-starting effective version
        if r.key not in seen:
            seen.add(r.key)
            out.append(r)
    return out


def history(db: Session, tenant_id: str, kind: str, key: str) -> list[BusinessRecord]:
    return (
        db.query(BusinessRecord).filter_by(tenant_id=tenant_id, kind=kind, key=key)
        .order_by(BusinessRecord.version.desc()).all()
    )


def open_draft(db: Session, tenant_id: str, kind: str, key: str) -> Optional[BusinessRecord]:
    return db.query(BusinessRecord).filter_by(tenant_id=tenant_id, kind=kind, key=key, status="draft").first()


# ─── validation ───────────────────────────────────────────────────────────────────────────────────────────

def validate_record(db: Session, tenant_id: str, rec: BusinessRecord, at: Optional[date] = None) -> dict:
    """{"errors": [...], "warnings": [...]}. Errors block publishing. Schema errors cannot occur for a stored record (writes
    validate), but are rechecked so a hand-edited row is caught."""
    from app.models.property import Property

    at = at or tenant_today(db, tenant_id)
    model, errors = validate_data(rec.kind, rec.data)
    warnings: list[str] = []
    if model is None:
        return {"errors": errors, "warnings": warnings}

    def published(kind: str, key: str) -> bool:
        return get_effective(db, tenant_id, kind, key, at) is not None

    if rec.kind == "package":
        missing = [k for k in model.destination_keys if not published("destination", k)]
        if missing:
            errors.append(f"destination(s) not published: {missing}")
        if model.vehicle_property_ids:
            props = db.query(Property).filter(Property.tenant_id == tenant_id, Property.id.in_(model.vehicle_property_ids)).all()
            if len(props) != len(set(model.vehicle_property_ids)):
                errors.append("a listed vehicle does not exist in this workspace")
            for p in props:
                cap = (p.max_adults or 0) + (p.max_children or 0)
                if cap and model.max_guests > cap:
                    errors.append(f"max_guests {model.max_guests} exceeds the capacity of {p.name} ({cap})")
        if all(r.valid_to < at for r in model.rates):
            warnings.append("every rate window has already ended: no price can be quoted from this package")
        if not model.inclusions:
            warnings.append("no inclusions are listed")
        if not model.exclusions:
            warnings.append("no exclusions are listed (guests will be told only what is included)")
    elif rec.kind == "destination":
        if model.distance_km_from_base > 0 and model.travel_hours_from_base == 0:
            errors.append("travel_hours_from_base is 0 for a destination that is not at the base: enter the real travel time")
    elif rec.kind == "itinerary":
        if not published("destination", model.destination_key):
            errors.append(f"destination '{model.destination_key}' is not published")
        missing = [k for k in model.package_keys if not published("package", k)]
        if missing:
            errors.append(f"package(s) not published: {missing}")
    elif rec.kind == "reseller_terms":
        missing = sorted({k for t in model.tiers for k in t.applies_to_package_keys if not published("package", k)})
        if missing:
            errors.append(f"package(s) not published: {missing}")
        policy = get_effective(db, tenant_id, "discount_policy", SINGLETON_KEY, at)
        if policy is not None:
            limit = parse(policy).max_discount_percent
            for t in model.tiers:
                if t.max_discount_percent > limit:
                    errors.append(f"tier '{t.name}' allows {t.max_discount_percent}% discount; the discount policy maximum is {limit}%")
        else:
            warnings.append("no discount policy is published: reseller discounts cannot be checked against a limit")
    if rec.kind in REQUIRES_CONFIRMATION and not getattr(model, "confirmed_by_ratha", False):
        errors.append("this policy has not been confirmed by Ratha (set confirmed_by_ratha only when Ratha has confirmed the terms)")
    return {"errors": errors, "warnings": warnings}


def _referenced_by(db: Session, tenant_id: str, kind: str, key: str, at: date) -> list[str]:
    """Published records that refer to this one (blocks deactivation)."""
    users: list[str] = []
    if kind == "destination":
        for r in list_effective(db, tenant_id, "package", at):
            if key in (r.data or {}).get("destination_keys", []):
                users.append(f"package '{r.key}'")
        for r in list_effective(db, tenant_id, "itinerary", at):
            if (r.data or {}).get("destination_key") == key:
                users.append(f"itinerary '{r.key}'")
    elif kind == "package":
        for r in list_effective(db, tenant_id, "itinerary", at):
            if key in (r.data or {}).get("package_keys", []):
                users.append(f"itinerary '{r.key}'")
        for t in (parse(r) for r in list_effective(db, tenant_id, "reseller_terms", at)):
            if any(key in tier.applies_to_package_keys for tier in t.tiers):
                users.append("the reseller terms")
    return users


# ─── writing ──────────────────────────────────────────────────────────────────────────────────────────────

def _audit(db: Session, tenant_id: str, action: str, actor: Optional[str], rec: BusinessRecord, **payload) -> None:
    append_audit(
        db, tenant_id=tenant_id, action=f"business_record.{action}", actor_user_id=actor,
        target_type="business_record", target_id=rec.id,
        payload={"kind": rec.kind, "key": rec.key, "version": rec.version, **payload},
    )


def create_draft(
    db: Session, tenant_id: str, kind: str, key: Optional[str], data: dict, actor_id: Optional[str],
    effective_from: Optional[date] = None, effective_to: Optional[date] = None, note: Optional[str] = None,
    rollback_of_id: Optional[str] = None,
) -> BusinessRecord:
    key = normalise_key(kind, key)
    model, problems = validate_data(kind, data)
    if model is None:
        raise BusinessDataError("invalid", "The data is not valid.", problems)
    if open_draft(db, tenant_id, kind, key) is not None:
        raise BusinessDataError("draft_exists", "There is already an unpublished draft for this record; edit or reject it first.", status=409)
    if effective_from and effective_to and effective_to < effective_from:
        raise BusinessDataError("invalid", "effective_to is before effective_from.", ["effective_to: before effective_from"])

    for attempt in (1, 2):
        latest = max((r.version for r in history(db, tenant_id, kind, key)), default=0)
        rec = BusinessRecord(
            tenant_id=tenant_id, kind=kind, key=key, version=latest + 1, status="draft", data=canonical(model),
            effective_from=effective_from, effective_to=effective_to, change_note=note, created_by=actor_id,
            rollback_of_id=rollback_of_id,
        )
        try:
            with db.begin_nested():
                db.add(rec)
                db.flush()
            break
        except IntegrityError:                        # another request took this version number: take the next one
            db.expire_all()
            if attempt == 2:
                raise BusinessDataError("conflict", "Could not allocate a version number; try again.", status=409)
    _audit(db, tenant_id, "draft_created", actor_id, rec, rollback_of=rollback_of_id)
    return rec


def update_draft(
    db: Session, tenant_id: str, record_id: str, actor_id: Optional[str], data: Optional[dict] = None,
    effective_from: Optional[date] = None, effective_to: Optional[date] = None, note: Optional[str] = None,
    set_dates: bool = False,
) -> BusinessRecord:
    rec = _get(db, tenant_id, record_id)
    if rec.status != "draft":
        raise BusinessDataError("not_a_draft", "Only a draft can be edited. Published versions never change; create a new draft.", status=409)
    before = rec.data
    if data is not None:
        model, problems = validate_data(rec.kind, data)
        if model is None:
            raise BusinessDataError("invalid", "The data is not valid.", problems)
        rec.data = canonical(model)
    if set_dates:
        rec.effective_from, rec.effective_to = effective_from, effective_to
    if note is not None:
        rec.change_note = note
    db.flush()
    _audit(db, tenant_id, "draft_updated", actor_id, rec, changes=diff_data(before, rec.data)[:50])
    return rec


def authored_by(db: Session, tenant_id: str, rec: BusinessRecord, user_id: Optional[str]) -> bool:
    """Did this user create or edit this draft? (The audit chain records every edit with its actor.)"""
    from app.models.audit_event import AuditEvent
    if not user_id:
        return False
    if rec.created_by == user_id:
        return True
    db.flush()
    return db.query(AuditEvent.id).filter(
        AuditEvent.tenant_id == tenant_id, AuditEvent.target_id == rec.id, AuditEvent.actor_user_id == user_id,
        AuditEvent.action == "business_record.draft_updated",
    ).first() is not None


def publish(
    db: Session, tenant_id: str, record_id: str, actor_id: Optional[str], effective_from: Optional[date] = None,
    actor_role: Optional[str] = None,
) -> BusinessRecord:
    """`actor_role` (given by the API) turns on the four-eyes rule: whoever drafted or edited a version may not publish it,
    unless they are the owner (the same rule as Marketing Studio approvals)."""
    rec = _get(db, tenant_id, record_id)
    if rec.status != "draft":
        raise BusinessDataError("not_a_draft", f"Only a draft can be published (this is {rec.status}).", status=409)
    if actor_role is not None and actor_role != "owner" and authored_by(db, tenant_id, rec, actor_id):
        raise BusinessDataError("self_approval", "You drafted or edited this version, so someone else must approve it.", status=403)
    result = validate_record(db, tenant_id, rec)
    if result["errors"]:
        raise BusinessDataError("invalid", "This draft cannot be published yet.", result["errors"])

    today = tenant_today(db, tenant_id)
    eff = effective_from or rec.effective_from or today
    if eff < today:
        raise BusinessDataError("invalid", "A version cannot take effect in the past.", ["effective_from: in the past"])
    others = [r for r in history(db, tenant_id, rec.kind, rec.key) if r.status == "published" and r.id != rec.id]
    # A version already in force (or starting today) is simply replaced; one still SCHEDULED to start on/after the new date is a conflict.
    later = [r for r in others if r.effective_from and (r.effective_from > eff or (r.effective_from == eff and r.effective_from > today))]
    if later:
        raise BusinessDataError(
            "scheduled_conflict", "Another version is already scheduled to start on or after that date; deactivate or roll it back first.",
            [f"version {r.version} starts {r.effective_from}" for r in later], status=409,
        )
    current = next((r for r in sorted(others, key=lambda r: (r.effective_from or date.min, r.version), reverse=True)
                    if r.effective_to is None or r.effective_to >= eff), None)

    claimed = db.execute(
        update(BusinessRecord)
        .where(BusinessRecord.id == rec.id, BusinessRecord.tenant_id == tenant_id, BusinessRecord.status == "draft")
        .values(status="published", effective_from=eff, effective_to=rec.effective_to, published_by=actor_id,
                published_at=datetime.now(timezone.utc), supersedes_id=current.id if current else None)
        .execution_options(synchronize_session=False)
    ).rowcount
    if claimed != 1:
        db.expire_all()
        raise BusinessDataError("not_a_draft", "This draft was already published or rejected.", status=409)
    db.expire(rec)

    changes: list[dict] = []
    if current is not None:
        changes = diff_data(current.data, rec.data)
        current.effective_to = eff - timedelta(days=1)
        if current.effective_to < today:              # the new version is in force now: the old one is history
            current.status = "superseded"
    db.flush()
    _audit(db, tenant_id, "published", actor_id, rec, effective_from=eff.isoformat(),
           supersedes_version=current.version if current else None, changes=changes[:100], warnings=result["warnings"])
    return rec


def reject(db: Session, tenant_id: str, record_id: str, actor_id: Optional[str], reason: Optional[str] = None) -> BusinessRecord:
    rec = _get(db, tenant_id, record_id)
    claimed = db.execute(
        update(BusinessRecord)
        .where(BusinessRecord.id == rec.id, BusinessRecord.tenant_id == tenant_id, BusinessRecord.status == "draft")
        .values(status="rejected", rejected_by=actor_id, rejected_reason=(reason or "")[:500] or None)
        .execution_options(synchronize_session=False)
    ).rowcount
    if claimed != 1:
        db.expire_all()
        raise BusinessDataError("not_a_draft", "Only a draft can be rejected.", status=409)
    db.expire(rec)
    _audit(db, tenant_id, "rejected", actor_id, rec, reason=reason)
    return rec


def deactivate(db: Session, tenant_id: str, kind: str, key: str, actor_id: Optional[str], note: Optional[str] = None) -> list[BusinessRecord]:
    key = normalise_key(kind, key)
    today = tenant_today(db, tenant_id)
    live = [r for r in history(db, tenant_id, kind, key) if r.status == "published"]
    if not live:
        raise BusinessDataError("not_found", "Nothing is published under that key.", status=404)
    users = _referenced_by(db, tenant_id, kind, key, today)
    if users:
        raise BusinessDataError("in_use", "This record is still used by published records.", users, status=409)
    for r in live:
        r.status = "inactive"
        r.effective_to = min(r.effective_to, today) if r.effective_to else today
        r.change_note = note or r.change_note
    db.flush()
    _audit(db, tenant_id, "deactivated", actor_id, live[0], versions=[r.version for r in live], note=note)
    return live


def rollback(
    db: Session, tenant_id: str, kind: str, key: str, to_version: int, actor_id: Optional[str],
    note: Optional[str] = None, publish_now: bool = False, actor_role: Optional[str] = None,
) -> BusinessRecord:
    """A NEW draft copied from an older version (history is never rewritten); optionally published straight away."""
    key = normalise_key(kind, key)
    src = next((r for r in history(db, tenant_id, kind, key) if r.version == to_version), None)
    if src is None or src.status in ("draft", "rejected"):
        raise BusinessDataError("not_found", "That version cannot be rolled back to.", status=404)
    draft = create_draft(db, tenant_id, kind, key, src.data, actor_id, note=note or f"Rollback to version {to_version}", rollback_of_id=src.id)
    _audit(db, tenant_id, "rolled_back", actor_id, draft, to_version=to_version)
    return publish(db, tenant_id, draft.id, actor_id, actor_role=actor_role) if publish_now else draft
