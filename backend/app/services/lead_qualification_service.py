"""
Lead qualification engine — Leads360 restructure Phase 4 (§5).

Scope note (verified against the actual codebase, not the original plan
draft): inbound WhatsApp/Instagram messages do NOT currently auto-create
an Inquiry row -- only the manual POST /inquiries staff endpoint and the
call-ingest workers (call_ingest.py, dograh_call_processor.py) do. So this
module is qualification *evaluation* infrastructure only: it computes
whether an inquiry's currently-known field values satisfy the tenant's
required_for_lead fields, and is meant to be called incrementally as new
signals arrive (progressive qualification, per the plan). It does NOT gate
inquiry creation -- there is no chat-triggered creation path to gate yet.
Wiring an auto-create-from-chat flow through this is a deliberately
separate, not-yet-scoped follow-up.
"""
from sqlalchemy.orm import Session
from app.models.inquiry import Inquiry
from app.services import lead_field_service
import structlog

log = structlog.get_logger()

UNQUALIFIED = "unqualified"
PENDING = "pending"
QUALIFIED = "qualified"


def evaluate_qualification(db: Session, tenant_id: str, inquiry: Inquiry) -> str:
    """
    Return the qualification status implied by the inquiry's current field
    values against the tenant's required_for_lead fields.

      - No required fields configured for the tenant → always "qualified"
        (qualification is opt-in; a tenant that hasn't defined criteria
        gets today's behavior of every inquiry counting as a lead).
      - All required fields have a non-empty value → "qualified"
      - At least one has a value but not all → "pending"
      - None have a value yet → "unqualified"
    """
    fields = lead_field_service.list_field_definitions(db, tenant_id)
    required = [f for f in fields if f.required_for_lead]
    if not required:
        return QUALIFIED

    filled = 0
    for f in required:
        value = lead_field_service.get_field_value(db, tenant_id, inquiry, f)
        if value not in (None, "", []):
            filled += 1

    if filled == len(required):
        return QUALIFIED
    if filled == 0:
        return UNQUALIFIED
    return PENDING


def refresh_qualification_status(db: Session, tenant_id: str, inquiry: Inquiry) -> str:
    """Evaluate and persist inquiry.qualification_status. Caller must commit."""
    status = evaluate_qualification(db, tenant_id, inquiry)
    if inquiry.qualification_status != status:
        log.info(
            "lead_qualification_changed", inquiry_id=inquiry.id,
            from_status=inquiry.qualification_status, to_status=status,
        )
        inquiry.qualification_status = status
    return status
