"""
Pipeline stage CRUD endpoints — Leads360 restructure Phase 1.

Real per-tenant authoring of the sales pipeline (add/reorder/delete),
replacing the old /tenants/me/pipeline-config endpoints which only let a
tenant rename/recolor/reorder/hide a fixed set of 7 enum-backed keys.
Those legacy endpoints are left in place (tenants.py) until the frontend
is migrated over to this API.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.v1.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.schemas.pipeline_stage import (
    PipelineStageOut, PipelineStageCreate, PipelineStageUpdate,
    PipelineStageReorder, PipelineStageDelete,
)
from app.services import pipeline_stage_service as svc

router = APIRouter(prefix="/pipeline-stages", tags=["pipeline-stages"])


def _to_out(stage, lead_counts: dict) -> PipelineStageOut:
    out = PipelineStageOut.model_validate(stage)
    out.lead_count = lead_counts.get(stage.id, 0)
    return out


@router.get("", response_model=list[PipelineStageOut])
def list_pipeline_stages(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stages = svc.list_stages(db, current_user.tenant_id)
    lead_counts = svc.lead_counts_by_stage(db, current_user.tenant_id)
    return [_to_out(s, lead_counts) for s in stages]


@router.post("", response_model=PipelineStageOut, status_code=201)
def create_pipeline_stage(
    body: PipelineStageCreate,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    try:
        stage = svc.create_stage(
            db, current_user.tenant_id,
            key=body.key, label=body.label, color=body.color, order=body.order,
            is_closed_won=body.is_closed_won, is_closed_lost=body.is_closed_lost,
            created_by=current_user.id,
        )
        db.commit()
    except svc.PipelineStageError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    return _to_out(stage, {})


@router.patch("/{stage_id}", response_model=PipelineStageOut)
def update_pipeline_stage(
    stage_id: str,
    body: PipelineStageUpdate,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    try:
        stage = svc.update_stage(
            db, current_user.tenant_id, stage_id,
            **body.model_dump(exclude_unset=True),
        )
        db.commit()
    except svc.PipelineStageError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    lead_counts = svc.lead_counts_by_stage(db, current_user.tenant_id)
    return _to_out(stage, lead_counts)


@router.put("/reorder", response_model=list[PipelineStageOut])
def reorder_pipeline_stages(
    body: PipelineStageReorder,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    try:
        stages = svc.reorder_stages(db, current_user.tenant_id, body.stage_ids_in_order)
        db.commit()
    except svc.PipelineStageError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    lead_counts = svc.lead_counts_by_stage(db, current_user.tenant_id)
    return [_to_out(s, lead_counts) for s in stages]


@router.delete("/{stage_id}", status_code=204)
def delete_pipeline_stage(
    stage_id: str,
    body: PipelineStageDelete,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    try:
        svc.delete_stage(db, current_user.tenant_id, stage_id, body.reassign_to_stage_id)
        db.commit()
    except svc.PipelineStageError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
