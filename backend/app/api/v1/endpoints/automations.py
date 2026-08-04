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

import structlog

from app.core.database import get_db
from app.api.v1.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.models.automation import AutomationRule, AutomationRun
from app.schemas.action_execution import ExecuteActionRequest, ExecuteActionResponse

log = structlog.get_logger()

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
    # T2.1: DM counterpart of ig_comment_received. Same fast-path rationale --
    # the actual matching in process_instagram_dm.py is inline, not through
    # fire_trigger, but this registration keeps CRUD validation and
    # automation_runs auditability consistent.
    "ig_dm_received",
}

VALID_ACTIONS = {
    "send_whatsapp_template", "create_draft_reply",
    "notify_team", "move_to_followup", "tag_guest",
    # T2.3: deterministic canned-text/card send for keyword-matched IG DMs
    # and comments. Dispatched inline from the ingest tasks, not through
    # fire_trigger (Architecture Decision #2) -- registered here so it
    # passes CRUD validation when a rule is created via the API.
    "send_instagram_quick_reply",
    # AI Autonomy Plan Phase 2 ticket 5: approve + queue-send a pending AI
    # draft (next_action_service.get_call_actions' one recognized action).
    "send_whatsapp_draft",
}


#: Actions a user may fire directly from an AI recommendation.
#: Deliberately a subset of VALID_ACTIONS, not the whole set: a rule author
#: configuring an automation is a different trust context from a one-click
#: button, so new actions are opted in here explicitly rather than by default.
#:
#: move_stage/assign_to/hold_dates/send_quote (AI Autonomy Plan Phase 2,
#: broader action-set expansion) are deliberately NOT added to VALID_ACTIONS:
#: move_stage and assign_to need a real accountable human actor (their
#: dispatch_action handlers take one explicitly, which only this endpoint
#: supplies), and hold_dates/send_quote are new enough not to expose in the
#: rule-authoring UI yet.
ONE_CLICK_ACTIONS = {
    "send_whatsapp_template", "create_draft_reply",
    "notify_team", "move_to_followup", "tag_guest",
    "send_whatsapp_draft",
    "move_stage", "assign_to", "hold_dates", "send_quote",
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


# ─── One-click execution of an AI recommendation ──────────────────────────────

@router.post("/actions/execute", response_model=ExecuteActionResponse)
def execute_recommended_action(
    payload: ExecuteActionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Execute a single AI-recommended action, right now, for one entity.

    Any authenticated user of the tenant may call this, matching
    conversations.py — which already lets any authenticated user approve and
    send a WhatsApp message. Gating the one-click form of the same send behind
    OWNER/MANAGER would be arbitrary. The real controls here are tenant scoping
    and ONE_CLICK_ACTIONS, which is a deliberate subset of VALID_ACTIONS.

    Every "AI suggested this — do it" button in the product posts here instead
    of each surface growing its own execute route. The action itself runs
    through automation_engine.dispatch_action, the same shared layer automation
    rules and the Flow Builder use, so an action behaves identically however it
    was triggered.

    This always runs inline rather than via Celery: the user is watching, and a
    fire-and-forget task could not tell them whether the send actually worked.
    Actions here are short (a template send, a stage move) — anything genuinely
    slow belongs in a rule, not on a button.

    Every execution is written to the audit chain, success or failure, so an
    outbound action can always be traced back to the person who clicked it.
    """
    if payload.action_type not in ONE_CLICK_ACTIONS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Action '{payload.action_type}' cannot be run from a recommendation. "
                f"Allowed: {sorted(ONE_CLICK_ACTIONS)}"
            ),
        )
    if payload.entity_refs.is_empty():
        raise HTTPException(status_code=422, detail="entity_refs must identify at least one entity")

    tenant_id = current_user.tenant_id
    target_type, target_id = payload.entity_refs.primary()

    # dispatch_action reads guest_id/inquiry_id straight off the context dict.
    context = payload.entity_refs.model_dump(exclude_none=True)

    status_str, detail, error = "success", "", None
    try:
        from app.workers.tasks.automation_engine import dispatch_action
        detail = dispatch_action(db, payload.action_type, payload.action_config, context, tenant_id, actor=current_user)
    except Exception as exc:
        status_str, error = "failed", str(exc)
        detail = f"Action failed: {exc}"
        log.warning(
            "one_click_action_failed",
            action=payload.action_type, tenant_id=tenant_id,
            target_type=target_type, target_id=target_id, error=str(exc),
        )

    # Audit before responding — an outbound action that is not recorded is worse
    # than one that fails, so this is written on the failure path too.
    audit_id = None
    try:
        from app.core.audit import append_audit
        event = append_audit(
            db,
            tenant_id=tenant_id,
            action="ai_recommendation.executed",
            actor_user_id=current_user.id,
            target_type=target_type,
            target_id=target_id,
            payload={
                "action_type": payload.action_type,
                "status": status_str,
                "source": payload.source,
                "entity_refs": context,
                "error": error,
            },
        )
        audit_id = event.id
    except Exception as exc:
        log.warning("one_click_action_audit_failed", error=str(exc), tenant_id=tenant_id)

    db.commit()

    if status_str == "failed":
        raise HTTPException(status_code=502, detail=detail)

    log.info(
        "one_click_action_executed",
        action=payload.action_type, tenant_id=tenant_id, actor=current_user.id,
        target_type=target_type, target_id=target_id,
    )
    return ExecuteActionResponse(
        status=status_str, action_type=payload.action_type,
        detail=detail or "Done", audit_id=audit_id,
    )
