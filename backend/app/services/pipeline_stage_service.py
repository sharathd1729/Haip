"""
Pipeline stage CRUD — real per-tenant authoring of the Leads360 pipeline
(add/reorder/delete stages), replacing the old rename-only cosmetic layer
over the fixed InquiryStage enum. See LEADS360_RESTRUCTURE_PLAN.md §2.
"""
from typing import Optional
from sqlalchemy.orm import Session
from app.models.pipeline_stage import PipelineStage
from app.models.inquiry import Inquiry
import structlog

log = structlog.get_logger()


class PipelineStageError(Exception):
    """Raised for any invalid pipeline-stage mutation; API layer converts to 4xx."""


def list_stages(db: Session, tenant_id: str) -> list[PipelineStage]:
    return (
        db.query(PipelineStage)
        .filter_by(tenant_id=tenant_id)
        .order_by(PipelineStage.order)
        .all()
    )


def lead_counts_by_stage(db: Session, tenant_id: str) -> dict[str, int]:
    from sqlalchemy import func
    rows = (
        db.query(Inquiry.stage_id, func.count(Inquiry.id))
        .filter(Inquiry.tenant_id == tenant_id, Inquiry.stage_id.isnot(None))
        .group_by(Inquiry.stage_id)
        .all()
    )
    return {stage_id: count for stage_id, count in rows}


def create_stage(
    db: Session, tenant_id: str, *, key: str, label: str, color: str,
    order: Optional[int], is_closed_won: bool, is_closed_lost: bool,
    created_by: Optional[str],
) -> PipelineStage:
    existing = db.query(PipelineStage).filter_by(tenant_id=tenant_id, key=key).first()
    if existing:
        raise PipelineStageError(f"A stage with key '{key}' already exists")

    if order is None:
        max_order = db.query(PipelineStage).filter_by(tenant_id=tenant_id).count()
        order = max_order

    stage = PipelineStage(
        tenant_id=tenant_id,
        key=key,
        label=label,
        color=color,
        order=order,
        is_default_entry=False,
        is_closed_won=is_closed_won,
        is_closed_lost=is_closed_lost,
        created_by=created_by,
    )
    db.add(stage)
    db.flush()
    log.info("pipeline_stage_created", tenant_id=tenant_id, stage_id=stage.id, key=key)
    return stage


def update_stage(
    db: Session, tenant_id: str, stage_id: str, *,
    label: Optional[str] = None, color: Optional[str] = None, order: Optional[int] = None,
    is_default_entry: Optional[bool] = None, is_closed_won: Optional[bool] = None,
    is_closed_lost: Optional[bool] = None, category: Optional[str] = None,
    is_valid_lead_entry: Optional[bool] = None, is_collab_entry: Optional[bool] = None,
) -> PipelineStage:
    stage = db.query(PipelineStage).filter_by(id=stage_id, tenant_id=tenant_id).first()
    if not stage:
        raise PipelineStageError("Stage not found")

    if label is not None:
        stage.label = label
    if color is not None:
        stage.color = color
    if order is not None:
        stage.order = order
    if is_closed_won is not None:
        if is_closed_won and is_closed_lost is not False and stage.is_closed_lost:
            raise PipelineStageError("A stage cannot be both closed-won and closed-lost")
        stage.is_closed_won = is_closed_won
    if is_closed_lost is not None:
        if is_closed_lost and stage.is_closed_won:
            raise PipelineStageError("A stage cannot be both closed-won and closed-lost")
        stage.is_closed_lost = is_closed_lost
    if category is not None:
        stage.category = category

    if is_default_entry is True:
        # Exactly one default-entry stage per tenant — clear the others.
        db.query(PipelineStage).filter(
            PipelineStage.tenant_id == tenant_id,
            PipelineStage.id != stage_id,
        ).update({"is_default_entry": False})
        stage.is_default_entry = True
    elif is_default_entry is False:
        raise PipelineStageError(
            "Cannot unset the default-entry stage directly — mark a different stage as default-entry instead"
        )

    # Lead auto-create routing targets (§ Leads360 chat auto-create) --
    # same "exactly one TRUE per tenant" convention as is_default_entry.
    if is_valid_lead_entry is True:
        db.query(PipelineStage).filter(
            PipelineStage.tenant_id == tenant_id,
            PipelineStage.id != stage_id,
        ).update({"is_valid_lead_entry": False})
        stage.is_valid_lead_entry = True
    elif is_valid_lead_entry is False:
        stage.is_valid_lead_entry = False

    if is_collab_entry is True:
        db.query(PipelineStage).filter(
            PipelineStage.tenant_id == tenant_id,
            PipelineStage.id != stage_id,
        ).update({"is_collab_entry": False})
        stage.is_collab_entry = True
    elif is_collab_entry is False:
        stage.is_collab_entry = False

    db.flush()
    log.info("pipeline_stage_updated", tenant_id=tenant_id, stage_id=stage_id)
    return stage


def reorder_stages(db: Session, tenant_id: str, stage_ids_in_order: list[str]) -> list[PipelineStage]:
    stages = list_stages(db, tenant_id)
    stage_by_id = {s.id: s for s in stages}
    if set(stage_ids_in_order) != set(stage_by_id.keys()):
        raise PipelineStageError("Reorder list must contain exactly the tenant's current stage IDs, no more, no fewer")

    for idx, sid in enumerate(stage_ids_in_order):
        stage_by_id[sid].order = idx
    db.flush()
    return list_stages(db, tenant_id)


def delete_stage(
    db: Session, tenant_id: str, stage_id: str, reassign_to_stage_id: Optional[str] = None,
) -> None:
    stage = db.query(PipelineStage).filter_by(id=stage_id, tenant_id=tenant_id).first()
    if not stage:
        raise PipelineStageError("Stage not found")

    total_stages = db.query(PipelineStage).filter_by(tenant_id=tenant_id).count()
    if total_stages <= 2:
        raise PipelineStageError("A pipeline must have at least 2 stages")

    lead_count = db.query(Inquiry).filter_by(tenant_id=tenant_id, stage_id=stage_id).count()
    if lead_count > 0:
        if not reassign_to_stage_id:
            raise PipelineStageError(
                f"{lead_count} lead(s) are currently in this stage — "
                f"reassign_to_stage_id is required before it can be deleted"
            )
        target = db.query(PipelineStage).filter_by(id=reassign_to_stage_id, tenant_id=tenant_id).first()
        if not target:
            raise PipelineStageError("reassign_to_stage_id does not refer to a stage in this tenant's pipeline")
        if target.id == stage_id:
            raise PipelineStageError("Cannot reassign leads to the stage being deleted")
        db.query(Inquiry).filter_by(tenant_id=tenant_id, stage_id=stage_id).update({"stage_id": target.id})
        log.info(
            "pipeline_stage_leads_reassigned", tenant_id=tenant_id,
            from_stage_id=stage_id, to_stage_id=target.id, count=lead_count,
        )

    if stage.is_default_entry:
        raise PipelineStageError(
            "Cannot delete the default-entry stage — mark a different stage as default-entry first"
        )

    db.delete(stage)
    db.flush()
    log.info("pipeline_stage_deleted", tenant_id=tenant_id, stage_id=stage_id)
