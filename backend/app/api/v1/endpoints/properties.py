import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.api.v1.deps import get_current_user, require_roles
from app.models.user import User, UserRole
from app.models.property import Property, Room
from app.schemas.property import (
    PropertyOut, PropertyCreateRequest, PropertyUpdateRequest,
    RoomOut, RoomCreateRequest, RoomUpdateRequest,
)

router = APIRouter(prefix="/properties", tags=["properties"])


# ─── Properties ───────────────────────────────────────────────────────────────

@router.get("", response_model=List[PropertyOut])
def list_properties(
    limit: int = 500,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(Property)
        .filter_by(tenant_id=current_user.tenant_id, is_active=True)
        .order_by(Property.name)
        .limit(min(limit, 500))
        .all()
    )


@router.post("", response_model=PropertyOut, status_code=status.HTTP_201_CREATED)
def create_property(
    body: PropertyCreateRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    slug = body.slug or body.name.lower().replace(" ", "-")
    data = body.model_dump(exclude_none=True)
    data.pop("slug", None)

    prop = Property(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        slug=slug,
        **data,
    )
    db.add(prop)
    db.commit()
    db.refresh(prop)
    return prop


@router.get("/{property_id}", response_model=PropertyOut)
def get_property(
    property_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    prop = db.query(Property).filter_by(id=property_id, tenant_id=current_user.tenant_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop


@router.patch("/{property_id}", response_model=PropertyOut)
def update_property(
    property_id: str,
    body: PropertyUpdateRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    prop = db.query(Property).filter_by(id=property_id, tenant_id=current_user.tenant_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(prop, k, v)
    db.commit()
    db.refresh(prop)
    return prop


@router.delete("/{property_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_property(
    property_id: str,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    prop = db.query(Property).filter_by(id=property_id, tenant_id=current_user.tenant_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    prop.is_active = False
    db.commit()


# ─── Rooms (hotel sub-resource) ───────────────────────────────────────────────

@router.get("/{property_id}/rooms", response_model=List[RoomOut])
def list_rooms(
    property_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    prop = db.query(Property).filter_by(id=property_id, tenant_id=current_user.tenant_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return db.query(Room).filter_by(property_id=property_id, tenant_id=current_user.tenant_id, is_active=True).all()


@router.post("/{property_id}/rooms", response_model=RoomOut, status_code=status.HTTP_201_CREATED)
def create_room(
    property_id: str,
    body: RoomCreateRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    prop = db.query(Property).filter_by(id=property_id, tenant_id=current_user.tenant_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    # Prevent duplicate room numbers in the same property
    existing = db.query(Room).filter_by(
        property_id=property_id,
        tenant_id=current_user.tenant_id,
        room_number=body.room_number,
        is_active=True,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Room '{body.room_number}' already exists in this property")

    room = Room(
        id=str(uuid.uuid4()),
        tenant_id=current_user.tenant_id,
        property_id=property_id,
        room_number=body.room_number,
        room_type=body.room_type or "standard",
        floor=body.floor,
        capacity=body.capacity or 2,
        amenities=body.amenities or [],
    )
    db.add(room)
    db.commit()
    db.refresh(room)
    return room


@router.patch("/{property_id}/rooms/{room_id}", response_model=RoomOut)
def update_room(
    property_id: str,
    room_id: str,
    body: RoomUpdateRequest,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    room = db.query(Room).filter_by(
        id=room_id, property_id=property_id, tenant_id=current_user.tenant_id
    ).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(room, k, v)
    db.commit()
    db.refresh(room)
    return room


@router.delete("/{property_id}/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_room(
    property_id: str,
    room_id: str,
    current_user: User = Depends(require_roles(UserRole.OWNER, UserRole.MANAGER)),
    db: Session = Depends(get_db),
):
    room = db.query(Room).filter_by(
        id=room_id, property_id=property_id, tenant_id=current_user.tenant_id
    ).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    room.is_active = False
    db.commit()
