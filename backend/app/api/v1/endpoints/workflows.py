"""Lead workflows API.

  GET  /workflows/catalog                 owner, manager   every playbook: what it does, its settings, template status,
                                                           conflicts with old automation rules
  PUT  /workflows/settings                owner, manager   switch playbooks on/off, timings (audited before/after)
  POST /workflows/templates/lead-pack     owner, manager   add the lead-pack WhatsApp templates as drafts (never sent to Meta)
  GET  /workflows/activity                owner, manager   what the playbooks did or skipped, newest first
  GET  /leads/{id}/journey                leads.read       the lead's milestones (received ... proposal) + automations
  POST /leads/{id}/viewed                 leads.read       the lead page was opened (the only "an agent saw it" record)
  POST /leads/{id}/playbooks/pause        leads.write      stop / resume automatic messages on this lead (audited)

Lead visibility matches GET /leads/{id}: a non owner/manager only reaches their own and unassigned leads (404 otherwise,
like a lead of another workspace). No LLM and no sends here: playbooks run in Celery (lead_playbooks.py).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.v1.deps import require_roles
from app.core.audit import append_audit
from app.core.database import get_db
from app.models.inquiry import Inquiry
from app.models.lead_workflow import PlaybookAction
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import lead_journey_tracker as journey
from app.services import lead_playbook_catalog as cat
from app.services import lead_playbook_engine as engine
from app.services import lead_playbook_guards as guards
from app.services import lead_playbook_settings as pb_settings
from app.services import wa_lead_pack
from app.services.authz_service import require_capability

router = APIRouter(tags=["workflows"])
_MANAGERS = require_roles(UserRole.OWNER, UserRole.MANAGER)


class SettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    guest_cap_hours: Optional[int] = None
    daily_cap: Optional[int] = None
    bridge_quiet_minutes: Optional[int] = None
    playbooks: Optional[dict[str, dict]] = None


class PauseRequest(BaseModel):
    paused: bool


def _tenant(db: Session, user: User) -> Tenant:
    return db.query(Tenant).filter_by(id=user.tenant_id).first()


def _catalog(db: Session, tenant: Tenant) -> dict:
    s = pb_settings.get(tenant)
    templates = {t["name"]: t for t in wa_lead_pack.pack_out(db, tenant.id)}
    conflicts = guards.conflicting_rules(db, tenant.id)
    since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    counts: dict[str, dict[str, int]] = {}
    for key, st in db.query(PlaybookAction.playbook_key, PlaybookAction.status).filter(
            PlaybookAction.tenant_id == tenant.id, PlaybookAction.created_at >= since).all():
        counts.setdefault(key, {}).setdefault(st, 0)
        counts[key][st] += 1
    items = []
    for p in cat.CATALOG:
        tpl = templates.get(p["template"]) if p["template"] else None
        items.append({
            "key": p["key"], "code": p["code"], "name": p["name"], "kind": p["kind"], "built": p["built"],
            "trigger": p["trigger"], "actions": p["actions"], "stops": p["stops"],
            "settings": s["playbooks"][p["key"]],
            "template": {"name": p["template"], "status": tpl["status"] if tpl else None,
                         "in_pack": bool(tpl)} if p["template"] else None,
            "today": counts.get(p["key"], {}),
        })
    return {"enabled": s["enabled"], "guest_cap_hours": s["guest_cap_hours"], "daily_cap": s["daily_cap"],
            "bridge_quiet_minutes": s["bridge_quiet_minutes"], "playbooks": items,
            "templates": list(templates.values()), "conflicts": conflicts}


@router.get("/workflows/catalog")
def get_catalog(current_user: User = Depends(_MANAGERS), db: Session = Depends(get_db)):
    return _catalog(db, _tenant(db, current_user))


@router.put("/workflows/settings")
def put_settings(body: SettingsUpdate, current_user: User = Depends(_MANAGERS), db: Session = Depends(get_db)):
    tenant = _tenant(db, current_user)
    try:
        pb_settings.update(db, tenant, current_user.id, body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    db.refresh(tenant)
    return _catalog(db, tenant)


@router.post("/workflows/templates/lead-pack")
def create_lead_pack(current_user: User = Depends(_MANAGERS), db: Session = Depends(get_db)):
    return wa_lead_pack.create_drafts(db, current_user.tenant_id, current_user.id)


@router.get("/workflows/activity")
def get_activity(
    playbook: Optional[str] = Query(None, max_length=40),
    status_: Optional[str] = Query(None, alias="status", max_length=12),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(_MANAGERS),
    db: Session = Depends(get_db),
):
    q = db.query(PlaybookAction).filter(PlaybookAction.tenant_id == current_user.tenant_id)
    if playbook:
        q = q.filter(PlaybookAction.playbook_key == playbook)
    if status_:
        q = q.filter(PlaybookAction.status == status_)
    rows = q.order_by(PlaybookAction.created_at.desc()).limit(limit).all()
    names = {}
    gids = {r.guest_id for r in rows if r.guest_id}
    if gids:
        from app.models.guest import Guest
        names = dict(db.query(Guest.id, Guest.name).filter(Guest.tenant_id == current_user.tenant_id, Guest.id.in_(gids)).all())
    return {"items": [{**journey.action_out(r), "guest_name": names.get(r.guest_id)} for r in rows]}


def _visible_inquiry(db: Session, user: User, inquiry_id: str) -> Inquiry:
    inquiry = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=user.tenant_id).first()
    if inquiry is None or (
        user.role not in (UserRole.OWNER, UserRole.MANAGER) and inquiry.assigned_to not in (None, user.id)
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead not found")
    return inquiry


@router.get("/leads/{inquiry_id}/journey")
def get_journey(inquiry_id: str, current_user: User = Depends(require_capability("leads.read")), db: Session = Depends(get_db)):
    inquiry = _visible_inquiry(db, current_user, inquiry_id)
    out = journey.journey_out(db, current_user.tenant_id, inquiry)
    db.commit()     # journey_out may have created the row on first read
    return out


@router.post("/leads/{inquiry_id}/viewed")
def mark_viewed(inquiry_id: str, current_user: User = Depends(require_capability("leads.read")), db: Session = Depends(get_db)):
    inquiry = _visible_inquiry(db, current_user, inquiry_id)
    out = journey.record_view(db, current_user.tenant_id, inquiry.id, current_user.id)
    db.commit()
    return out or {}


@router.post("/leads/{inquiry_id}/playbooks/pause")
def pause_playbooks(inquiry_id: str, body: PauseRequest, current_user: User = Depends(require_capability("leads.write")),
                    db: Session = Depends(get_db)):
    inquiry = _visible_inquiry(db, current_user, inquiry_id)
    row = journey.ensure(db, inquiry)
    before = bool(row.playbooks_paused_at)
    if body.paused != before:
        row.playbooks_paused_at = datetime.now(timezone.utc) if body.paused else None
        row.playbooks_paused_by = current_user.id if body.paused else None
        stopped = engine.stop_runs(db, current_user.tenant_id, inquiry.id, "paused by staff") if body.paused else 0
        append_audit(db, tenant_id=current_user.tenant_id, actor_user_id=current_user.id,
                     action="workflows.lead_paused" if body.paused else "workflows.lead_resumed",
                     target_type="inquiry", target_id=inquiry.id, payload={"stopped_runs": stopped})
    db.commit()
    return {"paused": bool(row.playbooks_paused_at),
            "paused_at": row.playbooks_paused_at.isoformat() if row.playbooks_paused_at else None}

