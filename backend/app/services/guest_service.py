"""Guest business logic — upsert, timeline, DPDP deletion."""
import uuid
import phonenumbers
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquiryStage
from app.models.call import Call
from app.models.conversation import Conversation, Message
from app.models.property import Stay
from app.models.transcript import Transcript
from app.models.score import CallScore
from app.models.consent import Consent
import structlog

log = structlog.get_logger()


def normalize_phone(phone: str) -> str:
    try:
        parsed = phonenumbers.parse(phone, "IN")
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except Exception:
        return phone


def upsert_by_phone(db: Session, tenant_id: str, phone: str, **kwargs) -> Guest:
    """Find guest by E.164 phone or create. kwargs: name, email, language_pref."""
    e164 = normalize_phone(phone)
    guest = db.query(Guest).filter_by(tenant_id=tenant_id, phone=e164, is_deleted=False).first()
    if not guest:
        guest = Guest(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            phone=e164,
            name=kwargs.get("name", "Unknown Guest"),
            email=kwargs.get("email"),
            language_pref=kwargs.get("language_pref", "en"),
        )
        db.add(guest)
        db.flush()
        log.info("guest_created", guest_id=guest.id, phone=e164, tenant_id=tenant_id)
    else:
        # Update fields if provided
        if kwargs.get("name") and guest.name == "Unknown Guest":
            guest.name = kwargs["name"]
        if kwargs.get("email") and not guest.email:
            guest.email = kwargs["email"]
    return guest


def get_timeline(db: Session, tenant_id: str, guest_id: str) -> dict:
    """Return a unified timeline of calls, messages, and stays for Guest 360."""
    calls = db.query(Call).filter_by(tenant_id=tenant_id, guest_id=guest_id).order_by(Call.created_at.desc()).limit(20).all()
    conversations = db.query(Conversation).filter_by(tenant_id=tenant_id, guest_id=guest_id).all()
    stays = db.query(Stay).filter_by(tenant_id=tenant_id, guest_id=guest_id).all()
    inquiries = db.query(Inquiry).filter_by(tenant_id=tenant_id, guest_id=guest_id).all()

    events = []
    for c in calls:
        events.append({"type": "call", "id": c.id, "at": c.started_at or c.created_at.isoformat(), "data": {
            "direction": c.direction.value if hasattr(c.direction, "value") else c.direction,
            "duration_sec": c.duration_seconds,
            "ai_score": float(c.ai_score) if c.ai_score else None,
            "disposition": c.human_disposition or (c.ai_disposition.value if c.ai_disposition else None),
        }})
    for s in stays:
        events.append({"type": "stay", "id": s.id, "at": s.check_in, "data": {
            "check_in": s.check_in, "check_out": s.check_out,
            "property_id": s.property_id, "amount": float(s.total_amount) if s.total_amount else None,
        }})

    events.sort(key=lambda e: e["at"] or "", reverse=True)
    return {
        "guest_id": guest_id,
        "events": events,
        "open_inquiries": [i.id for i in inquiries if i.stage not in (InquiryStage.BOOKED, InquiryStage.LOST, InquiryStage.GHOSTED)],
        "total_stays": len(stays),
        "total_calls": len(calls),
    }


def dpdp_delete(db: Session, tenant_id: str, guest_id: str) -> dict:
    """
    DPDP deletion: hard-delete all PII-bearing rows, tombstone the guest.
    Caller must commit after this returns.
    """
    # Hard-delete child data
    conv_ids = [c.id for c in db.query(Conversation.id).filter_by(tenant_id=tenant_id, guest_id=guest_id)]
    if conv_ids:
        db.query(Message).filter(Message.conversation_id.in_(conv_ids)).delete(synchronize_session=False)
    db.query(Conversation).filter_by(tenant_id=tenant_id, guest_id=guest_id).delete()

    call_ids = [c.id for c in db.query(Call.id).filter_by(tenant_id=tenant_id, guest_id=guest_id)]
    if call_ids:
        db.query(Transcript).filter(Transcript.call_id.in_(call_ids)).delete(synchronize_session=False)
        db.query(CallScore).filter(CallScore.call_id.in_(call_ids)).delete(synchronize_session=False)
    db.query(Call).filter_by(tenant_id=tenant_id, guest_id=guest_id).delete()

    db.query(Inquiry).filter_by(tenant_id=tenant_id, guest_id=guest_id).delete()
    db.query(Stay).filter_by(tenant_id=tenant_id, guest_id=guest_id).delete()
    db.query(Consent).filter_by(tenant_id=tenant_id, guest_id=guest_id).delete()

    # Tombstone guest — anonymise PII, keep id for audit referential integrity
    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
    if guest:
        guest.phone = f"DELETED_{guest_id[:8]}"
        guest.email = None
        guest.name = "[Deleted]"
        guest.is_deleted = True
        guest.deleted_at = datetime.now(timezone.utc)

    log.info("dpdp_deletion_completed", tenant_id=tenant_id, guest_id=guest_id)
    return {"status": "deleted", "guest_id": guest_id}
