"""
Lead Field Registry service — Leads360 restructure Phase 3 (§4).

Two responsibilities that were originally asked for separately but
unified here into one catalog: which fields render on a lead's detail
view (show_in_detail), and which fields must be present for a message to
count as a qualified lead (required_for_lead, consumed by
lead_qualification_service in Phase 4).
"""
from typing import Optional, Any
from sqlalchemy.orm import Session
from app.models.lead_field_definition import LeadFieldDefinition
from app.models.inquiry import Inquiry
import structlog

log = structlog.get_logger()

# Fields backed by a real Inquiry column, keyed by field_key (seeded set).
# guest_name/phone are derived from the related Guest/GuestIdentity rows,
# not a column on Inquiry itself, so they're read specially in
# get_field_value() rather than via getattr(inquiry, column_name).
_DERIVED_FIELD_KEYS = {"guest_name", "phone"}


class LeadFieldError(Exception):
    pass


def list_field_definitions(db: Session, tenant_id: str) -> list[LeadFieldDefinition]:
    return (
        db.query(LeadFieldDefinition)
        .filter_by(tenant_id=tenant_id)
        .order_by(LeadFieldDefinition.display_order)
        .all()
    )


def create_field_definition(
    db: Session, tenant_id: str, *, field_key: str, label: str, data_type: str,
    required_for_lead: bool, show_in_detail: bool,
) -> LeadFieldDefinition:
    existing = db.query(LeadFieldDefinition).filter_by(tenant_id=tenant_id, field_key=field_key).first()
    if existing:
        raise LeadFieldError(f"A field with key '{field_key}' already exists")

    max_order = db.query(LeadFieldDefinition).filter_by(tenant_id=tenant_id).count()
    field = LeadFieldDefinition(
        tenant_id=tenant_id, field_key=field_key, label=label, data_type=data_type,
        source="custom", column_name=None,
        show_in_detail=show_in_detail, required_for_lead=required_for_lead,
        display_order=max_order,
    )
    db.add(field)
    db.flush()
    log.info("lead_field_created", tenant_id=tenant_id, field_key=field_key)
    return field


def update_field_definition(
    db: Session, tenant_id: str, field_id: str, **patch: Any,
) -> LeadFieldDefinition:
    field = db.query(LeadFieldDefinition).filter_by(id=field_id, tenant_id=tenant_id).first()
    if not field:
        raise LeadFieldError("Field not found")
    for k, v in patch.items():
        if v is not None:
            setattr(field, k, v)
    db.flush()
    return field


def delete_field_definition(db: Session, tenant_id: str, field_id: str) -> None:
    field = db.query(LeadFieldDefinition).filter_by(id=field_id, tenant_id=tenant_id).first()
    if not field:
        raise LeadFieldError("Field not found")
    db.delete(field)
    db.flush()


def get_field_value(db: Session, tenant_id: str, inquiry: Inquiry, field: LeadFieldDefinition) -> Optional[Any]:
    """Resolve one field's current value for a given inquiry."""
    if field.field_key == "guest_name":
        return inquiry.guest.name if inquiry.guest else None
    if field.field_key == "phone":
        return inquiry.guest.phone if inquiry.guest else None
    if field.source == "column" and field.column_name:
        value = getattr(inquiry, field.column_name, None)
        if value is not None and hasattr(value, "__float__") and field.data_type in ("currency", "number"):
            try:
                return float(value)
            except (TypeError, ValueError):
                return value
        return value
    # source == "custom" -- lives in Inquiry.custom_fields JSON
    return (inquiry.custom_fields or {}).get(field.field_key)


def get_field_values_for_inquiry(
    db: Session, tenant_id: str, inquiry: Inquiry, detail_only: bool = True,
) -> list[dict]:
    fields = list_field_definitions(db, tenant_id)
    if detail_only:
        fields = [f for f in fields if f.show_in_detail]
    return [
        {
            "field_key": f.field_key,
            "label": f.label,
            "data_type": f.data_type,
            "value": get_field_value(db, tenant_id, inquiry, f),
        }
        for f in fields
    ]
