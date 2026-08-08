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
    """
    Find guest by E.164 phone or create, using the Identity Resolution Engine.
    kwargs: name, email, language_pref, source
    """
    from app.services.identity_service import resolve_gid, add_signal
    e164 = normalize_phone(phone)
    guest_id, _ = resolve_gid(
        db=db,
        tenant_id=tenant_id,
        signal_type="phone",
        value=e164,
        source=kwargs.pop("source", "system"),
        guest_fields={"name": kwargs.get("name"), "email": kwargs.get("email"),
                      "language_pref": kwargs.get("language_pref", "en")},
    )
    guest = db.query(Guest).filter_by(id=guest_id, is_deleted=False).first()

    # Update name/email on the guest row if enriched
    if guest:
        if kwargs.get("name") and (not guest.name or guest.name == "Unknown Guest"):
            guest.name = kwargs["name"]
        if kwargs.get("email") and not guest.email:
            guest.email = kwargs["email"]
            # Also enrich the identity graph with the email signal
            add_signal(db, tenant_id, guest_id, "email", kwargs["email"], source="system")

    return guest


def upsert_by_channel_thread(
    db: Session,
    tenant_id: str,
    channel_thread_id: str,
    ota_guest_id: Optional[str] = None,
    source: str = "channel_manager",
    **kwargs,
) -> tuple[Guest, bool]:
    """
    M3 — Channel Manager identity flow.
    Resolve or create a guest from an OTA thread ID.
    Returns (guest, created).
    """
    from app.services.identity_service import resolve_gid, add_signal

    guest_id, created = resolve_gid(
        db=db,
        tenant_id=tenant_id,
        signal_type="channel_thread_id",
        value=channel_thread_id,
        source=source,
        guest_fields={"name": kwargs.get("name"), "email": kwargs.get("email")},
    )

    # Also attach the OTA guest ID if available
    if ota_guest_id:
        add_signal(db, tenant_id, guest_id, "ota_guest_id", ota_guest_id, source=source)

    guest = db.query(Guest).filter_by(id=guest_id, is_deleted=False).first()
    return guest, created


def enrich_guest_from_booking(
    db: Session,
    tenant_id: str,
    guest_id: str,
    booking_id: str,
    phone: Optional[str] = None,
    email: Optional[str] = None,
) -> None:
    """
    M3 — Called when a Channel Manager booking is confirmed and OTA releases contact details.
    Enriches the existing guest profile with phone, email, and booking_id.
    """
    from app.services.identity_service import add_signal

    add_signal(db, tenant_id, guest_id, "booking_id", booking_id, source="channel_manager")
    if phone:
        e164 = normalize_phone(phone)
        add_signal(db, tenant_id, guest_id, "phone", e164, source="channel_manager")
        # Keep phone column in sync for fast lookups
        guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tenant_id).first()
        if guest and not guest.phone:
            guest.phone = e164
            db.add(guest)
    if email:
        add_signal(db, tenant_id, guest_id, "email", email.lower().strip(),
                   source="channel_manager")


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
        # migration 071: Stay.check_in/check_out are real DATE columns now
        # -- isoformat() so "at" stays a string across every event type
        # (calls' "at" is a string); events.sort() below compares "at"
        # values against each other and raises TypeError mixing str/date.
        ci_str = s.check_in.isoformat() if s.check_in else None
        co_str = s.check_out.isoformat() if s.check_out else None
        events.append({"type": "stay", "id": s.id, "at": ci_str, "data": {
            "check_in": ci_str, "check_out": co_str,
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

    # guest_events carries message previews and AI summaries — PII-bearing, so
    # it must be purged here like every other child table. Missing it would
    # leave a readable copy of the guest's conversation behind after a DPDP
    # deletion request.
    from app.models.guest_event import GuestEvent
    db.query(GuestEvent).filter_by(tenant_id=tenant_id, guest_id=guest_id).delete()

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
