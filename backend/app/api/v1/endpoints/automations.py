"""
Automation rules CRUD and run-log endpoints.

GET    /automations              list rules for tenant
POST   /automations              create rule
PATCH  /automations/{id}         update (toggle active, rename, etc.)
DELETE /automations/{id}         delete rule + its runs

GET    /automations/runs          recent runs for tenant  (?limit=20)
GET    /automations/runs/{run_id} single run detail
"""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.api.v1.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.models.automation import AutomationRule, AutomationRun

router = APIRouter(prefix="/automations", tags=["automations"])

# ─── Pydantic schemas ─────────────────────────────────────────────────────────

class RuleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    trigger: str
    trigger_config: Optional[dict] = {}
    action: str
    action_config: Optional[dict] = {}
    is_active: bool = True


class RuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    trigger: Optional[str] = None
    trigger_config: Optional[dict] = None
    action: Optional[str] = None
    action_config: Optional[dict] = None
    is_active: Optional[bool] = None


class RuleOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    trigger: str
    trigger_config: dict
    action: str
    action_config: dict
    is_active: bool
    run_count: int
    last_run_at: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_safe(cls, obj: AutomationRule) -> "RuleOut":
        return cls(
            id=obj.id,
            name=obj.name,
            description=obj.description,
            trigger=obj.trigger,
            trigger_config=obj.trigger_config or {},
            action=obj.action,
            action_config=obj.action_config or {},
            is_active=obj.is_active,
            run_count=obj.run_count or 0,
            last_run_at=obj.last_run_at.isoformat() if obj.last_run_at else None,
            created_at=obj.created_at.isoformat() if obj.created_at else None,
        )


class RunOut(BaseModel):
    id: str
    automation_id: str
    automation_name: Optional[str] = None
    status: str
    trigger_event: Optional[str] = None
    context: dict
    detail: Optional[str] = None
    error: Optional[str] = None
    ran_at: str

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_safe(cls, obj: AutomationRun) -> "RunOut":
        return cls(
            id=obj.id,
            automation_id=obj.automation_id,
            automation_name=obj.automation_name,
            status=obj.status,
            trigger_event=obj.trigger_event,
            context=obj.context or {},
            detail=obj.detail,
            error=obj.error,
            ran_at=obj.ran_at.isoformat() if obj.ran_at else "",
        )


# ─── Validation ───────────────────────────────────────────────────────────────

VALID_TRIGGERS = {
    "new_inquiry", "call_completed",
    "no_response_2h", "no_response_24h",
    "inquiry_lost",
    "stay_check_in_1d", "stay_check_out_1d",
    # T1.3: registered so automation_runs can log outcomes consistently with
    # every other trigger, and so non-keyword actions (e.g. notify_team) can
    # attach to comment events without new plumbing. Phase 2's keyword-match
    # fast path in process_instagram_comment.py bypasses fire_trigger entirely
    # for latency reasons (Architecture Decision #2) -- this registration is
    # about consistency/auditability, not the dispatch path itself.
    "ig_comment_received",
}

VALID_ACTIONS = {
    "send_whatsapp_template", "create_draft_reply",
    "notify_team", "move_to_followup", "tag_guest",
}


def _validate(trigger: str, action: str):
    if trigger not in VALID_TRIGGERS:
        raise HTTPException(status_code=422, detail=f"Unknown trigger: {trigger}")
    if action not in VALID_ACTIONS:
        raise HTTPException(status_code=422, detail=f"Unknown action: {action}")


# ─── Rules endpoints ──────────────────────────────────────────────────────────

@router.get("", response_model=List[RuleOut])
def list_rules(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rules = (
        db.query(AutomationRule)
        .filter_by(tenant_id=current_user.tenant_id)
        .order_by(AutomationRule.created_at.desc())
        .all()
    )
    return [RuleOut.from_orm_safe(r) for r in rules]


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(
    body: RuleCreate,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    _validate(body.trigger, body.action)
    rule = AutomationRule(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        name=body.name.strip(),
        description=body.description,
        trigger=body.trigger,
        trigger_config=body.trigger_config or {},
        action=body.action,
        action_config=body.action_config or {},
        is_active=body.is_active,
        run_count=0,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return RuleOut.from_orm_safe(rule)


@router.patch("/{rule_id}", response_model=RuleOut)
def update_rule(
    rule_id: str,
    body: RuleUpdate,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    rule = db.query(AutomationRule).filter_by(id=rule_id, tenant_id=current_user.tenant_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    update_data = body.model_dump(exclude_unset=True)
    trigger = update_data.get("trigger", rule.trigger)
    action = update_data.get("action", rule.action)
    _validate(trigger, action)

    for field, value in update_data.items():
        setattr(rule, field, value)
    rule.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(rule)
    return RuleOut.from_orm_safe(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(
    rule_id: str,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    rule = db.query(AutomationRule).filter_by(id=rule_id, tenant_id=current_user.tenant_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()


# ─── Runs endpoints ───────────────────────────────────────────────────────────

@router.get("/runs", response_model=List[RunOut])
def list_runs(
    limit: int = Query(default=20, ge=1, le=100),
    automation_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(AutomationRun).filter_by(tenant_id=current_user.tenant_id)
    if automation_id:
        q = q.filter_by(automation_id=automation_id)
    runs = q.order_by(AutomationRun.ran_at.desc()).limit(limit).all()
    return [RunOut.from_orm_safe(r) for r in runs]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    run = db.query(AutomationRun).filter_by(id=run_id, tenant_id=current_user.tenant_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunOut.from_orm_safe(run)
