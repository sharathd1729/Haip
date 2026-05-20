"""
W15 / K11 — Saved views: persistent named filter combinations per user or tenant.
"""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.api.v1.deps import get_current_user
from app.models.user import User
from app.models.saved_view import SavedView

router = APIRouter(prefix="/saved-views", tags=["saved-views"])


class SavedViewIn(BaseModel):
    name: str
    scope: str          # "inbox" | "inquiries"
    filter_json: dict = {}
    sort: Optional[str] = None
    is_shared: bool = False


class SavedViewOut(BaseModel):
    id: str
    name: str
    scope: str
    filter_json: dict
    sort: Optional[str] = None
    is_shared: bool
    user_id: Optional[str] = None

    model_config = {"from_attributes": True}


@router.get("", response_model=List[SavedViewOut])
def list_saved_views(
    scope: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return views for the current user + tenant-shared views."""
    from sqlalchemy import or_
    q = db.query(SavedView).filter(
        SavedView.tenant_id == current_user.tenant_id,
    ).filter(
        or_(
            SavedView.user_id == current_user.id,
            SavedView.is_shared == True,
        )
    )
    if scope:
        q = q.filter(SavedView.scope == scope)
    return q.order_by(SavedView.name).all()


@router.post("", response_model=SavedViewOut, status_code=201)
def create_saved_view(
    body: SavedViewIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    view = SavedView(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        user_id=current_user.id if not body.is_shared else None,
        name=body.name,
        scope=body.scope,
        filter_json=body.filter_json,
        sort=body.sort,
        is_shared=body.is_shared,
    )
    db.add(view)
    db.commit()
    db.refresh(view)
    return view


@router.patch("/{view_id}", response_model=SavedViewOut)
def update_saved_view(
    view_id: str,
    body: SavedViewIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    view = db.query(SavedView).filter_by(id=view_id, tenant_id=current_user.tenant_id).first()
    if not view:
        raise HTTPException(status_code=404, detail="View not found")
    view.name        = body.name
    view.filter_json = body.filter_json
    view.sort        = body.sort
    view.is_shared   = body.is_shared
    db.commit()
    db.refresh(view)
    return view


@router.delete("/{view_id}", status_code=204)
def delete_saved_view(
    view_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    view = db.query(SavedView).filter_by(id=view_id, tenant_id=current_user.tenant_id).first()
    if not view:
        raise HTTPException(status_code=404, detail="View not found")
    db.delete(view)
    db.commit()
