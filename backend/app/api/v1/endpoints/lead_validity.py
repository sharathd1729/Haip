"""The automatic valid-lead rule's settings (lead_validity; KPI catalogue D-28). Owner / manager; audited.

GET /lead-validity/settings   the workspace's rule ({enabled, require_name, require_phone, require_check_in, require_location,
                              allowed_locations, location_field}) + the location fields to choose from
PUT /lead-validity/settings   change it (any subset of the keys); audited lead_validity.settings_changed with before/after.
                              PATCH /tenants/me refuses brand_config.lead_validity, so this is the only way to change it.
"""
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.v1.deps import require_roles
from app.core.database import get_db
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import lead_validity

router = APIRouter(prefix="/lead-validity", tags=["leads360"])
_OWNERS = require_roles(UserRole.OWNER, UserRole.MANAGER)

FIELD_LABELS = {"guest_location": "Guest location (lead page)", "pickup": "Pickup point", "guest_city": "Guest city (guest profile)"}


class ValiditySettingsIn(BaseModel):
    enabled: Optional[bool] = None
    require_name: Optional[bool] = None
    require_phone: Optional[bool] = None
    require_check_in: Optional[bool] = None
    require_location: Optional[bool] = None
    allowed_locations: Optional[List[str]] = Field(default=None, max_length=20)
    location_field: Optional[Literal["guest_location", "pickup", "guest_city"]] = None


def _out(cfg: dict) -> dict:
    return {**cfg, "location_fields": [{"value": k, "label": v} for k, v in FIELD_LABELS.items()]}


@router.get("/settings")
def get_settings(current_user: User = Depends(_OWNERS), db: Session = Depends(get_db)) -> dict:
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    return _out(lead_validity.settings_of(tenant))


@router.put("/settings")
def put_settings(body: ValiditySettingsIn, current_user: User = Depends(_OWNERS), db: Session = Depends(get_db)) -> dict:
    tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
    data = body.model_dump(exclude_none=True)
    if "allowed_locations" in data:
        data["allowed_locations"] = [x.strip()[:60] for x in data["allowed_locations"] if x and x.strip()]
    cfg = lead_validity.put_settings(db, tenant, current_user, data)
    db.commit()
    return _out(cfg)
