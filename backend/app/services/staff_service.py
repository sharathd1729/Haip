"""Staff profiles (operations module). Staff are not guests: see find_active_staff_by_phone and workers/tasks/whatsapp.py."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.ops import StaffDuty, StaffProfile
from app.models.property import Property
from app.models.user import User
from app.schemas.ops import DutyAssignment, StaffCreate, StaffUpdate
from app.services import phone_identity


def normalize_phone(db: Session, tenant_id: str, raw: str) -> str:
    phone = phone_identity.normalize(raw, phone_identity.region_for_tenant(db, tenant_id))
    if not phone:
        raise HTTPException(status_code=422, detail="That phone number isn't a valid mobile number.")
    return phone


def find_active_staff_by_phone(db: Session, tenant_id: str, phone: Optional[str]) -> Optional[StaffProfile]:
    """The active staff profile for this number in this tenant, or None. Used on every inbound WhatsApp message."""
    if not phone:
        return None
    normalized = phone_identity.normalize(phone) or phone
    return (
        db.query(StaffProfile)
        .filter(StaffProfile.tenant_id == tenant_id, StaffProfile.phone_e164 == normalized, StaffProfile.active.is_(True))
        .first()
    )


def duties_of(db: Session, tenant_id: str, staff_ids: list[str]) -> dict[str, list[DutyAssignment]]:
    out: dict[str, list[DutyAssignment]] = {sid: [] for sid in staff_ids}
    if not staff_ids:
        return out
    for d in db.query(StaffDuty).filter(StaffDuty.tenant_id == tenant_id, StaffDuty.staff_id.in_(staff_ids)).all():
        out.setdefault(d.staff_id, []).append(DutyAssignment(duty=d.duty, property_id=d.property_id))
    return out


def to_out(db: Session, staff: StaffProfile, duties: Optional[list[DutyAssignment]] = None) -> dict:
    if duties is None:
        duties = duties_of(db, staff.tenant_id, [staff.id]).get(staff.id, [])
    return {
        "id": staff.id, "name": staff.name, "phone_e164": staff.phone_e164, "user_id": staff.user_id,
        "languages": staff.languages or [], "whatsapp_opt_in_at": staff.whatsapp_opt_in_at, "active": staff.active,
        "notes": staff.notes, "duties": duties,
    }


def list_staff(db: Session, tenant_id: str, include_inactive: bool = False) -> list[dict]:
    q = db.query(StaffProfile).filter(StaffProfile.tenant_id == tenant_id)
    if not include_inactive:
        q = q.filter(StaffProfile.active.is_(True))
    rows = q.order_by(StaffProfile.name).all()
    duties = duties_of(db, tenant_id, [s.id for s in rows])
    return [to_out(db, s, duties.get(s.id, [])) for s in rows]


def get_staff(db: Session, tenant_id: str, staff_id: str) -> StaffProfile:
    staff = db.query(StaffProfile).filter_by(id=staff_id, tenant_id=tenant_id).first()
    if staff is None:
        raise HTTPException(status_code=404, detail="Staff member not found")
    return staff


def _check_refs(db: Session, tenant_id: str, user_id: Optional[str], duties: list[DutyAssignment]) -> None:
    if user_id and db.query(User.id).filter_by(id=user_id, tenant_id=tenant_id).first() is None:
        raise HTTPException(status_code=422, detail="user_id is not a user in this workspace")
    for d in duties:
        if d.property_id and db.query(Property.id).filter_by(id=d.property_id, tenant_id=tenant_id).first() is None:
            raise HTTPException(status_code=422, detail="property_id is not a property in this workspace")


def _replace_duties(db: Session, tenant_id: str, staff_id: str, duties: list[DutyAssignment]) -> None:
    db.query(StaffDuty).filter_by(tenant_id=tenant_id, staff_id=staff_id).delete(synchronize_session=False)
    seen = set()
    for d in duties:
        key = (d.duty, d.property_id)
        if key in seen:
            continue
        seen.add(key)
        db.add(StaffDuty(tenant_id=tenant_id, staff_id=staff_id, duty=d.duty, property_id=d.property_id))


def _phone_taken(db: Session, tenant_id: str, phone: str, except_id: Optional[str] = None) -> bool:
    q = db.query(StaffProfile.id).filter(StaffProfile.tenant_id == tenant_id, StaffProfile.phone_e164 == phone)
    if except_id:
        q = q.filter(StaffProfile.id != except_id)
    return q.first() is not None


def create_staff(db: Session, tenant_id: str, body: StaffCreate) -> StaffProfile:
    phone = normalize_phone(db, tenant_id, body.phone)
    if _phone_taken(db, tenant_id, phone):
        raise HTTPException(status_code=409, detail="A staff member with this phone number already exists")
    _check_refs(db, tenant_id, body.user_id, body.duties)
    staff = StaffProfile(
        tenant_id=tenant_id, user_id=body.user_id, name=body.name.strip(), phone_e164=phone,
        languages=body.languages, notes=body.notes, active=True,
        whatsapp_opt_in_at=datetime.now(timezone.utc) if body.whatsapp_opt_in else None,
    )
    db.add(staff)
    db.flush()
    _replace_duties(db, tenant_id, staff.id, body.duties)
    db.flush()
    return staff


def update_staff(db: Session, tenant_id: str, staff_id: str, body: StaffUpdate) -> StaffProfile:
    staff = get_staff(db, tenant_id, staff_id)
    data = body.model_dump(exclude_unset=True)
    if "phone" in data and data["phone"]:
        phone = normalize_phone(db, tenant_id, data["phone"])
        if _phone_taken(db, tenant_id, phone, except_id=staff.id):
            raise HTTPException(status_code=409, detail="A staff member with this phone number already exists")
        staff.phone_e164 = phone
    if "user_id" in data or "duties" in data:
        _check_refs(db, tenant_id, data.get("user_id"), body.duties or [])
    for field in ("name", "user_id", "languages", "active", "notes"):
        if field in data:
            setattr(staff, field, data[field].strip() if field == "name" else data[field])
    if "whatsapp_opt_in" in data:
        if data["whatsapp_opt_in"] and not staff.whatsapp_opt_in_at:
            staff.whatsapp_opt_in_at = datetime.now(timezone.utc)
        elif not data["whatsapp_opt_in"]:
            staff.whatsapp_opt_in_at = None
    if body.duties is not None:
        _replace_duties(db, tenant_id, staff.id, body.duties)
    db.flush()
    return staff
