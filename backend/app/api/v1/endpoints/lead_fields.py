"""Lead Field Registry CRUD endpoints — Leads360 restructure Phase 3."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.v1.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.schemas.lead_field_definition import (
    LeadFieldDefinitionOut, LeadFieldDefinitionCreate, LeadFieldDefinitionUpdate,
)
from app.services import lead_field_service as svc

router = APIRouter(prefix="/lead-fields", tags=["lead-fields"])


@router.get("", response_model=list[LeadFieldDefinitionOut])
def list_lead_fields(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return svc.list_field_definitions(db, current_user.tenant_id)


@router.post("", response_model=LeadFieldDefinitionOut, status_code=201)
def create_lead_field(
    body: LeadFieldDefinitionCreate,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    try:
        field = svc.create_field_definition(
            db, current_user.tenant_id,
            field_key=body.field_key, label=body.label, data_type=body.data_type,
            required_for_lead=body.required_for_lead, show_in_detail=body.show_in_detail,
        )
        db.commit()
    except svc.LeadFieldError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    return field


@router.patch("/{field_id}", response_model=LeadFieldDefinitionOut)
def update_lead_field(
    field_id: str,
    body: LeadFieldDefinitionUpdate,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    try:
        field = svc.update_field_definition(
            db, current_user.tenant_id, field_id, **body.model_dump(exclude_unset=True),
        )
        db.commit()
    except svc.LeadFieldError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    return field


@router.delete("/{field_id}", status_code=204)
def delete_lead_field(
    field_id: str,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    try:
        svc.delete_field_definition(db, current_user.tenant_id, field_id)
        db.commit()
    except svc.LeadFieldError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
