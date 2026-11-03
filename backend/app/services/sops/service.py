"""SOP instances: start, view, tick, evidence, customise, checks. Every write is audited (append_audit).

Progress is per step key and remembers the step_sha it was done against: a new version keeps the tick of an unchanged
step; a changed step shows "Changed since you did it" and counts as to do. Evidence (screenshots) is a media_assets row
source "sop_evidence", status "evidence", so it never reaches the photo library or a post. Links are https and shown only,
never fetched.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.media_asset import MediaAsset
from app.models.property import Property
from app.models.sop import SopInstance, SopStepProgress, SopVersion
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.sops import PatchIn, StartIn
from app.services import website_seo
from app.services.sops import checks
from app.services.sops.catalogue import BY_KEY, TEMPLATES, applies


class SopError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _now() -> datetime:
    return datetime.now(UTC)


def _audit(db: Session, inst: SopInstance, action: str, actor_id: str | None, **payload) -> None:
    append_audit(
        db,
        tenant_id=inst.tenant_id,
        action=action,
        actor_user_id=actor_id,
        target_type="sop_instance",
        target_id=inst.id,
        payload={"template": inst.template_key, **payload, **({} if actor_id else {"actor": "system"})},
    )


def can_work(db: Session, user: User, inst: SopInstance) -> bool:
    from app.services.authz_service import has_capability

    return (
        inst.assignee_id == user.id or has_capability(db, user, "sops.work") or has_capability(db, user, "sops.manage")
    )


def get(db: Session, tenant_id: str, instance_id: str) -> SopInstance:
    inst = db.query(SopInstance).filter_by(id=instance_id, tenant_id=tenant_id).first()
    if inst is None:
        raise SopError(404, "not_found", "No such checklist in this workspace.")
    return inst


def _user_in_tenant(db: Session, tenant_id: str, user_id: str) -> None:
    if db.query(User.id).filter_by(id=user_id, tenant_id=tenant_id, is_active=True).first() is None:
        raise SopError(422, "bad_assignee", "Pick someone from your team.")


def start(db: Session, tenant: Tenant, body: StartIn, actor_id: str) -> SopInstance:
    t = BY_KEY.get(body.template_key)
    kind = website_seo.business_kind(tenant.business_type)
    if t is None or not applies(t, kind):
        raise SopError(422, "unknown_template", "That checklist is not available for this business.")
    if body.property_id:
        if t.per_property == "no":
            raise SopError(422, "no_property", "This checklist is for the whole business, not one property.")
        if db.query(Property.id).filter_by(id=body.property_id, tenant_id=tenant.id).first() is None:
            raise SopError(404, "property_not_found", "No such property in this workspace.")
    elif t.per_property == "required":
        raise SopError(422, "property_needed", "Choose the property this checklist is for.")
    assignee = body.assignee_id
    if assignee:
        _user_in_tenant(db, tenant.id, assignee)
    else:
        owner = db.query(User.id).filter_by(tenant_id=tenant.id, role=UserRole.OWNER, is_active=True).first()
        assignee = owner[0] if owner else actor_id
    inst = SopInstance(
        tenant_id=tenant.id,
        template_key=t.key,
        property_id=body.property_id,
        target_key=body.property_id or "",
        assignee_id=assignee,
        started_by=actor_id,
        generating="queued",
    )
    try:
        with db.begin_nested():
            db.add(inst)
            db.flush()
    except IntegrityError:
        raise SopError(409, "already_started", "This checklist is already running. Open it from the list.") from None
    now = _now()
    for s in t.steps:
        db.add(
            SopStepProgress(
                tenant_id=tenant.id,
                instance_id=inst.id,
                cycle_no=1,
                step_key=s.key,
                due_at=now + timedelta(days=s.due_days),
            )
        )
    db.flush()
    _audit(db, inst, "sop.started", actor_id, property_id=body.property_id, assignee_id=assignee)
    return inst


def queue_regenerate(db: Session, inst: SopInstance, actor_id: str) -> None:
    if inst.status == "archived":
        raise SopError(409, "archived", "This checklist is archived.")
    inst.generating = "queued"
    _audit(db, inst, "sop.regenerate_requested", actor_id)


def _progress(db: Session, inst: SopInstance) -> dict[str, SopStepProgress]:
    return {
        p.step_key: p
        for p in db.query(SopStepProgress).filter_by(
            tenant_id=inst.tenant_id, instance_id=inst.id, cycle_no=inst.cycle_no
        )
    }


def _version(db: Session, inst: SopInstance) -> SopVersion | None:
    return db.get(SopVersion, inst.current_version_id) if inst.current_version_id else None


def _steps(db: Session, inst: SopInstance) -> list[dict]:
    """Current version's steps + the workspace's own extra steps, with progress, minus hidden ones."""
    v = _version(db, inst)
    ov = inst.overrides or {}
    hidden = set(ov.get("hidden_steps") or [])
    steps = list(v.steps) if v else []
    steps += [
        {
            "key": e["key"],
            "title": e["title"],
            "how": e.get("how", ""),
            "verify": "manual",
            "check": None,
            "values": [],
            "needs": [],
            "notes": [],
            "rules": [],
            "categories": None,
            "photos": None,
            "link": None,
            "step_sha": "custom",
            "custom": True,
        }
        for e in ov.get("extra_steps") or []
    ]
    prog = _progress(db, inst)
    out = []
    for s in steps:
        p = prog.get(s["key"])
        status = p.status if p else "todo"
        changed = status == "done" and p.step_sha not in (s["step_sha"], None) and not s.get("custom")
        out.append(
            {
                **s,
                "hidden": s["key"] in hidden,
                "status": "todo" if changed else status,
                "changed": changed,
                "due_at": p.due_at.isoformat() if p and p.due_at else None,
                "done_at": p.done_at.isoformat() if p and p.done_at and not changed else None,
                "done_by": p.done_by if p else None,
                "evidence": {"asset_id": p.evidence_asset_id, "url": p.evidence_url}
                if p and (p.evidence_asset_id or p.evidence_url)
                else None,
                "check_result": p.check_result if p else None,
            }
        )
    return out


def _counts(steps: list[dict]) -> dict:
    live = [s for s in steps if not s["hidden"]]
    return {"done": sum(s["status"] in ("done", "skipped") for s in live), "total": len(live)}


def view(db: Session, tenant: Tenant, inst: SopInstance) -> dict:
    t = BY_KEY[inst.template_key]
    v = _version(db, inst)
    steps = _steps(db, inst)
    return {
        **summary(db, inst, steps),
        "summary": t.summary,
        "steps": steps,
        "version": {
            "no": v.version_no,
            "reason": v.reason,
            "created_at": v.created_at.isoformat() if v.created_at else None,
            "ai": bool(v.model),
            "ai_note": v.ai_note,
        }
        if v
        else None,
        "overrides": inst.overrides or {},
    }


def summary(db: Session, inst: SopInstance, steps: list[dict] | None = None) -> dict:
    t = BY_KEY[inst.template_key]
    steps = steps if steps is not None else _steps(db, inst)
    due = [s["due_at"] for s in steps if not s["hidden"] and s["status"] == "todo" and s["due_at"]]
    return {
        "id": inst.id,
        "template_key": t.key,
        "platform": t.platform,
        "title": t.title,
        "recurrence": t.recurrence,
        "status": inst.status,
        "property_id": inst.property_id,
        "property_name": (db.get(Property, inst.property_id).name if inst.property_id else None),
        "assignee_id": inst.assignee_id,
        "preparing": inst.generating == "queued" or inst.current_version_id is None,
        "next_due_at": min(due) if due else None,
        **_counts(steps),
    }


def list_view(db: Session, tenant: Tenant) -> dict:
    kind = website_seo.business_kind(tenant.business_type)
    insts = (
        db.query(SopInstance)
        .filter(SopInstance.tenant_id == tenant.id, SopInstance.status != "archived")
        .order_by(SopInstance.created_at)
        .all()
    )
    running = {(i.template_key, i.target_key) for i in insts}
    from app.services.vehicle_pool import is_placeholder_name

    props = [
        p
        for p in db.query(Property)
        .filter(Property.tenant_id == tenant.id, Property.is_active.is_(True))
        .order_by(Property.name)
        if not is_placeholder_name(p.name)
    ]
    available = []
    for t in TEMPLATES:
        if not applies(t, kind):
            continue
        # a per-listing SOP is offered once per property; the others once for the whole business
        targets = [(p.id, p.name) for p in props] if t.per_property == "required" else [("", None)]
        for pid, pname in targets:
            if (t.key, pid) not in running:
                available.append(
                    {
                        "template_key": t.key,
                        "platform": t.platform,
                        "title": t.title,
                        "summary": t.summary,
                        "per_property": t.per_property,
                        "property_id": pid or None,
                        "property_name": pname,
                        "steps": len(t.steps),
                    }
                )
    return {"kind": kind, "instances": [summary(db, i) for i in insts], "available": available}


def _step(db: Session, inst: SopInstance, key: str) -> tuple[dict, SopStepProgress]:
    s = next((x for x in _steps(db, inst) if x["key"] == key), None)
    if s is None:
        raise SopError(404, "step_not_found", "No such step in this checklist.")
    p = _progress(db, inst).get(key)
    if p is None:
        p = SopStepProgress(tenant_id=inst.tenant_id, instance_id=inst.id, cycle_no=inst.cycle_no, step_key=key)
        db.add(p)
    return s, p


def _settle(inst: SopInstance, db: Session) -> None:
    c = _counts(_steps(db, inst))
    if inst.status == "active" and c["total"] and c["done"] == c["total"]:
        inst.status, inst.last_done_at = "done", _now()
    elif inst.status == "done" and c["done"] < c["total"]:
        inst.status = "active"


def mark(db: Session, inst: SopInstance, key: str, action: str, actor_id: str) -> dict:
    if inst.status in ("archived", "paused"):
        raise SopError(409, inst.status, f"This checklist is {inst.status}.")
    s, p = _step(db, inst, key)
    if action == "done":
        if s["verify"] in ("evidence", "auto") and not (p.evidence_asset_id or p.evidence_url):
            raise SopError(
                422,
                "evidence_needed",
                "Add a screenshot or link first."
                if s["verify"] == "evidence"
                else "HAIP checks this one: tap Check now, or add a screenshot if it can't check.",
            )
        p.status, p.step_sha, p.done_by, p.done_at = "done", s["step_sha"], actor_id, _now()
    elif action == "skip":
        p.status, p.step_sha, p.done_by, p.done_at = "skipped", s["step_sha"], actor_id, _now()
    else:
        p.status, p.done_by, p.done_at = "todo", None, None
    db.flush()
    _settle(inst, db)
    _audit(
        db,
        inst,
        {"done": "sop.step_done", "skip": "sop.step_skipped", "undo": "sop.step_undone"}[action],
        actor_id,
        step=key,
    )
    return s


def add_evidence_file(db: Session, inst: SopInstance, key: str, raw: bytes, content_type: str, actor_id: str) -> None:
    from app.services import media_storage
    from app.services.ops_fleet_service import check_file

    _step(db, inst, key)
    ext = check_file(raw, content_type)  # JPG/PNG/WebP/PDF, <= 5 MB, magic bytes (HTTPException 422)
    sha = hashlib.sha256(raw).hexdigest()
    ct = (content_type or "").split(";")[0].strip().lower()
    a = MediaAsset(
        tenant_id=inst.tenant_id,
        property_id=inst.property_id,
        storage_key=media_storage.upload_sop_evidence(inst.tenant_id, inst.id, key, sha, raw, ct, ext),
        mime_type=ct,
        bytes=len(raw),
        sha256=sha,
        source="sop_evidence",
        status="evidence",
        alt_text=f"Screenshot for {key}",
        created_by=actor_id,
    )
    db.add(a)
    db.flush()
    _s, p = _step(db, inst, key)
    p.evidence_asset_id = a.id
    db.flush()
    _audit(db, inst, "sop.evidence_added", actor_id, step=key, asset_id=a.id)


def add_evidence_link(db: Session, inst: SopInstance, key: str, url: str, actor_id: str) -> None:
    _s, p = _step(db, inst, key)
    p.evidence_url = url[:500]
    db.flush()
    _audit(db, inst, "sop.evidence_added", actor_id, step=key, url=url[:500])


def evidence_key(db: Session, inst: SopInstance, key: str) -> str:
    p = _progress(db, inst).get(key)
    a = (
        db.query(MediaAsset).filter_by(id=p.evidence_asset_id, tenant_id=inst.tenant_id).first()
        if p and p.evidence_asset_id
        else None
    )
    if a is None:
        raise SopError(404, "no_evidence", "No screenshot for this step.")
    return a.storage_key


def patch(db: Session, inst: SopInstance, body: PatchIn, actor_id: str) -> None:
    changes: dict = {}
    if body.assignee_id is not None:
        _user_in_tenant(db, inst.tenant_id, body.assignee_id)
        changes["assignee_id"] = [inst.assignee_id, body.assignee_id]
        inst.assignee_id = body.assignee_id
    if body.status is not None:
        changes["status"] = [inst.status, body.status]
        inst.status = body.status
    ov = dict(inst.overrides or {})
    if body.hidden_steps is not None:
        keys = {s.key for s in BY_KEY[inst.template_key].steps} | {e["key"] for e in ov.get("extra_steps") or []}
        if set(body.hidden_steps) - keys:
            raise SopError(422, "step_not_found", "No such step in this checklist.")
        changes["hidden_steps"], ov["hidden_steps"] = body.hidden_steps, body.hidden_steps
    if body.extra_steps is not None:
        if len({e.key for e in body.extra_steps}) != len(body.extra_steps):
            raise SopError(422, "duplicate_step", "Two of your own steps have the same key.")
        ov["extra_steps"] = [e.model_dump() for e in body.extra_steps]
        changes["extra_steps"] = len(body.extra_steps)
    inst.overrides = ov
    if inst.status in ("active", "done"):
        _settle(inst, db)
    _audit(db, inst, "sop.settings_changed", actor_id, changes=changes)


def run_checks(db: Session, tenant: Tenant, inst: SopInstance, actor_id: str | None = None) -> list[dict]:
    """Run every automatic step's check. ok = done by HAIP; fail = back to to-do if HAIP had ticked it; unknown = stays."""
    results = []
    for s in _steps(db, inst):
        if s["verify"] != "auto" or not s.get("check") or s["check"] not in checks.CHECKS:
            continue
        r = checks.run(s["check"], db, tenant, inst)
        _s, p = _step(db, inst, s["key"])
        p.check_result = r
        if r["result"] == "ok":
            p.status, p.step_sha, p.done_by, p.done_at = "done", s["step_sha"], None, _now()
        elif r["result"] == "fail" and p.status == "done" and p.done_by is None:
            p.status, p.done_at = "todo", None
        results.append({"step": s["key"], **r})
    db.flush()
    _settle(inst, db)
    _audit(db, inst, "sop.check_ran", actor_id, results=[{"step": r["step"], "result": r["result"]} for r in results])
    return results
