"""The Bookings agenda page (layout B).

  GET  /bookings/summary?month=YYYY-MM     bookings checking in that month; money only with revenue.read
  GET  /bookings/occupancy?days=14         each vehicle's bookings and holds from today
  POST /bookings/{id}/whatsapp-thread      the guest's WhatsApp conversation (opened if there is none), to send in it

Registered before booking_detail so "/bookings/summary" is never read as a booking id.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.v1.deps import get_current_user
from app.core.database import get_db
from app.models.property import Stay
from app.models.tenant import Tenant
from app.models.user import User
from app.services import booking_agenda_service as agenda
from app.services.authz_service import has_capability, require_capability

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.get("/summary")
def month_summary(month: Optional[str] = Query(None, pattern=r"^\d{4}-\d{2}$", description="YYYY-MM; default this month"),
                  current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
                  _cap=Depends(require_capability("bookings.read"))):
    today = agenda.tenant_today(db, current_user.tenant_id)
    try:
        first = date.fromisoformat(f"{month}-01") if month else today.replace(day=1)
    except ValueError:
        raise HTTPException(status_code=422, detail="month must be YYYY-MM")
    return agenda.month_summary(db, current_user.tenant_id, first, has_capability(db, current_user, "revenue.read"), today)


@router.get("/occupancy")
def vehicle_occupancy(days: int = Query(14, ge=1, le=62), current_user: User = Depends(get_current_user),
                      db: Session = Depends(get_db), _cap=Depends(require_capability("bookings.read"))):
    return agenda.occupancy(db, current_user.tenant_id, days)


@router.post("/{booking_id}/whatsapp-thread")
def whatsapp_thread(booking_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
                    _cap=Depends(require_capability("conversations.send"))):
    """The guest's open WhatsApp conversation, so the booking page can send in it with the inbox endpoints. A guest who
    never wrote on WhatsApp gets one opened here (a template is the only thing that can go in it)."""
    from app.services import wa_booking_messages
    stay = db.query(Stay).filter_by(id=booking_id, tenant_id=current_user.tenant_id).first()
    if not stay or not stay.guest_id:
        raise HTTPException(status_code=404, detail="Booking not found")
    state = agenda.whatsapp_state(db, current_user.tenant_id, stay.guest_id)
    if not state["conversation_id"]:
        tenant = db.query(Tenant).filter_by(id=current_user.tenant_id).first()
        conv = wa_booking_messages._open_conversation(db, tenant, stay.guest_id)
        if conv.source == "personal_bridge":     # one open WhatsApp thread per guest, and this one is the read-only mirror
            db.rollback()
            raise HTTPException(status_code=409, detail="This guest's WhatsApp chat is on the personal WhatsApp mirror, "
                                                        "which HAIP cannot send from.")
        state["conversation_id"] = conv.id
        db.commit()
    return state
