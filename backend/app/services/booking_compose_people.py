"""Who a new booking is for, and what it can start from: the guest search, the duplicate-number check, the guest card, the
saved quotes ("Start from") and the prefill when the flow opens from a lead, a guest or a quote. Read-only.

  * A guest card says what HAIP knows: open lead and its stage, past bookings, saved quotes, when they last wrote on WhatsApp
    (inside 24 hours a confirmation goes as a normal message, otherwise as the approved template). The phone shows its last
    four digits only.
  * Same number = same person (identity_service.find_person_by_phone), so a "new" guest with a known number is offered as
    that person instead.
  * Quotes listed: issued, waiting for approval, or already booked, on any of the guest's leads (newest first). A booked quote
    names the booking made from it ("automatically" when the guest paid its link).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.inquiry_360 import InquiryQuote
from app.models.property import Stay
from app.models.stay_finance import StayPaymentLink
from app.services import booking_clash as bc
from app.services import phone_identity
from app.services import quote_calc_leads as qcl
from app.services import quote_send_service as qss
from app.services.invoice_service import booking_ref

QUOTE_STATUSES = ("issued", "pending_approval", "accepted")


class PeopleError(Exception):
    def __init__(self, message: str, status: int = 404):
        super().__init__(message)
        self.message, self.status = message, status


def last4(phone: Optional[str]) -> Optional[str]:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return digits[-4:] if digits and not str(phone).startswith("DELETED_") else None


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def wrote_text(last: Optional[datetime], now: Optional[datetime] = None) -> Optional[str]:
    """"wrote 25 min ago", "wrote 2 h ago", "wrote yesterday", "last wrote Sat 17 Oct"."""
    if last is None:
        return None
    now = now or datetime.now(timezone.utc)
    ago = now - _aware(last)
    if ago < timedelta(hours=1):
        return f"wrote {max(1, int(ago.total_seconds() // 60))} min ago"
    if ago < timedelta(hours=24):
        return f"wrote {int(ago.total_seconds() // 3600)} h ago"
    if ago < timedelta(hours=48):
        return "wrote yesterday"
    return f"last wrote {bc.day(_aware(last).date())}"


def last_inbound(db: Session, tenant_id: str, guest_id: str) -> Optional[datetime]:
    return (db.query(func.max(Message.created_at)).join(Conversation, Conversation.id == Message.conversation_id)
            .filter(Message.tenant_id == tenant_id, Conversation.tenant_id == tenant_id, Conversation.guest_id == guest_id,
                    Conversation.channel == ChannelType.WHATSAPP, Message.direction == MessageDirection.INBOUND).scalar())


def _lead_trip(inq: Inquiry) -> str:
    bits = []
    if inq.route_mentioned:
        bits.append(str(inq.route_mentioned)[:60])
    try:
        ci = date.fromisoformat(str(inq.check_in)[:10]) if inq.check_in else None
        co = date.fromisoformat(str(inq.check_out)[:10]) if inq.check_out else None
    except ValueError:
        ci = co = None
    if ci:
        bits.append(f"{bc.day(ci)} → {bc.day(co)}" if co and co > ci else bc.day(ci))
    guests = (inq.adults or 0) + (inq.children or 0)
    if guests:
        bits.append(f"{guests} guest{'' if guests == 1 else 's'}")
    return ", ".join(bits)


def lead_view(inq: Inquiry, stages: dict) -> dict:
    label, _ = qcl._stage_label(inq, stages)
    src = inq.source.value if inq.source else None
    return {"inquiry_id": inq.id, "stage_label": label, "source": src, "source_label": qcl.SOURCE_LABEL.get(src or "", "Not recorded"),
            "open": qcl.is_open(inq, stages), "trip": _lead_trip(inq)}


def open_lead(db: Session, tenant_id: str, guest_id: str, stages: dict) -> Optional[Inquiry]:
    rows = (db.query(Inquiry).filter(Inquiry.tenant_id == tenant_id, Inquiry.guest_id == guest_id)
            .order_by(Inquiry.created_at.desc()).all())
    return next((i for i in rows if qcl.is_open(i, stages)), None)


def guest_card(db: Session, tenant_id: str, guest: Guest, stages: Optional[dict] = None) -> dict:
    stages = stages if stages is not None else qcl._stages(db, tenant_id)
    lead = open_lead(db, tenant_id, guest.id, stages)
    stays = (db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.guest_id == guest.id, Stay.status != "cancelled")
             .order_by(Stay.check_in.desc()).limit(1).all())
    lead_ids = [i for (i,) in db.query(Inquiry.id).filter(Inquiry.tenant_id == tenant_id, Inquiry.guest_id == guest.id).all()]
    quotes = (db.query(func.count(InquiryQuote.id)).filter(InquiryQuote.tenant_id == tenant_id, InquiryQuote.inquiry_id.in_(lead_ids),
                                                          InquiryQuote.status.in_(QUOTE_STATUSES)).scalar() if lead_ids else 0)
    lv = lead_view(lead, stages) if lead else None
    if lv and stays:
        tag = f"Past guest · lead {lv['stage_label']}"
    elif lv:
        tag = f"Lead · {lv['stage_label']}"
    elif stays:
        tag = "Booked · no open lead"
    else:
        tag = "Guest · no open lead"
    if lv and lv["trip"]:
        info = lv["trip"] + "."
    elif stays:
        s = stays[0]
        info = f"Last trip {bc.span(s.check_in, s.check_out)} ({booking_ref(s)}{', ' + s.property.name if s.property else ''})."
    else:
        info = ""
    last = last_inbound(db, tenant_id, guest.id)
    return {"guest_id": guest.id, "name": guest.name or "", "phone_last4": last4(guest.phone), "tag": tag, "info": info,
            "open_lead": lv, "quotes_count": int(quotes or 0), "wrote": wrote_text(last),
            "window_open": last is not None and datetime.now(timezone.utc) - _aware(last) <= timedelta(hours=24)}


def search(db: Session, tenant_id: str, text: str, limit: int = 6) -> dict:
    """{"results": [guest cards], "recent": bool}. No text = the people who wrote most recently on WhatsApp."""
    text = (text or "").strip()
    stages = qcl._stages(db, tenant_id)
    base = db.query(Guest).filter(Guest.tenant_id == tenant_id, Guest.is_deleted.is_(False))
    if not text:
        rows = (db.query(Conversation.guest_id, func.max(Message.created_at).label("at"))
                .join(Message, Message.conversation_id == Conversation.id)
                .filter(Conversation.tenant_id == tenant_id, Message.tenant_id == tenant_id, Message.direction == MessageDirection.INBOUND,
                        Conversation.channel == ChannelType.WHATSAPP)
                .group_by(Conversation.guest_id).order_by(func.max(Message.created_at).desc()).limit(limit).all())
        ids = [r[0] for r in rows]
        by_id = {g.id: g for g in base.filter(Guest.id.in_(ids)).all()} if ids else {}
        return {"results": [guest_card(db, tenant_id, by_id[i], stages) for i in ids if i in by_id], "recent": True}
    digits = "".join(ch for ch in text if ch.isdigit())
    conds = []
    if len(digits) < len(text.replace(" ", "").replace("+", "")):
        conds.append(Guest.name.ilike(f"%{text}%"))
    if len(digits) >= 3:
        conds.append(Guest.phone.like(f"%{digits[-10:]}%"))
    if not conds:
        return {"results": [], "recent": False}
    guests = base.filter(or_(*conds)).order_by(Guest.created_at.desc()).limit(limit).all()
    return {"results": [guest_card(db, tenant_id, g, stages) for g in guests], "recent": False}


def check_phone(db: Session, tenant_id: str, phone: str) -> dict:
    """{"valid", "digits", "existing": guest card | None} for the "Add a new guest" number."""
    from app.services.identity_service import find_person_by_phone
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    e164 = phone_identity.normalize(phone, phone_identity.region_for_tenant(db, tenant_id)) if len(digits) >= 10 else None
    existing = None
    if e164:
        gid = find_person_by_phone(db, tenant_id, e164)
        g = db.query(Guest).filter_by(id=gid, tenant_id=tenant_id, is_deleted=False).first() if gid else None
        existing = guest_card(db, tenant_id, g) if g else None
    return {"valid": bool(e164), "digits": len(digits), "existing": existing}


# ─── saved quotes ────────────────────────────────────────────────────────────────────────────────────────

def _sent_text(q: InquiryQuote) -> str:
    when = bc.day(_aware(q.shared_at).date()) if q.shared_at else None
    if q.status == "pending_approval":
        return "Waiting for the owner's OK"
    if q.shared_via == "sent":
        return f"Sent {when}" if when else "Sent on WhatsApp"
    if q.shared_via == "copied":
        return f"Copied {when}" if when else "Copied"
    return "Saved, not sent"


def _booked(db: Session, tenant_id: str, q: InquiryQuote) -> Optional[dict]:
    if q.status != "accepted":
        return None
    stay = (db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.inquiry_id == q.inquiry_id, Stay.status != "cancelled")
            .order_by(Stay.created_at.desc()).first())
    if stay is None:
        return None
    auto = db.query(StayPaymentLink.id).filter(StayPaymentLink.tenant_id == tenant_id, StayPaymentLink.inquiry_quote_id == q.id,
                                               StayPaymentLink.stay_id == stay.id).first() is not None
    return {"booking_id": stay.id, "ref": booking_ref(stay), "automatic": auto}


def prefill(q: InquiryQuote) -> dict:
    """What "Start from" fills in: package or custom trip, dates (times stay noon to noon; a same-day trip 10 am to 8 pm),
    guests, add-ons, discount, GST and the quoted total (the flow offers "Keep" when today's price differs)."""
    snap = q.snapshot or {}
    inputs = snap.get("inputs") or {}
    ci = q.check_in or (date.fromisoformat(inputs["check_in"]) if inputs.get("check_in") else None)
    co = q.check_out or (date.fromisoformat(inputs["check_out"]) if inputs.get("check_out") else None)
    same_day = snap.get("product") == "same_day" or (ci is not None and co is not None and co <= ci)
    if same_day and ci is not None:
        co = ci
    out: dict = {"check_in": ci.isoformat() if ci else None, "check_out": co.isoformat() if co else None,
                 "check_in_time": "10:00" if same_day else "12:00", "check_out_time": "20:00" if same_day else "12:00",
                 "guests": q.guests or (int(inputs.get("adults") or 0) + int(inputs.get("children") or 0)) or None,
                 "total": str(q.amount), "calculator": snap.get("kind") == "calculator"}
    if snap.get("kind") == "calculator":
        out.update(mode=inputs.get("mode") or "fixed", package_key=inputs.get("package_key"), custom=inputs.get("custom"),
                   addons=inputs.get("addons") or [], discount_percent=str(inputs.get("discount_percent") or "0"),
                   gst_percent=str(snap.get("gst_percent")) if snap.get("gst_percent") is not None else None,
                   prices_include_gst=snap.get("prices_include_gst"))
    elif q.package_key:
        out.update(mode="fixed", package_key=q.package_key)
    return out


def quote_card(db: Session, tenant_id: str, q: InquiryQuote, latest_id: Optional[str]) -> dict:
    snap = q.snapshot or {}
    booked = _booked(db, tenant_id, q)
    usable = q.status == "issued" and bool(q.is_active)
    why = None
    if q.status == "pending_approval":
        why = "Waiting for the owner's OK. It can be used once approved."
    elif q.status == "accepted" and booked is None:
        why = "Already booked."
    return {"quote_id": q.id, "number": qss.quote_number(q) + (" · option 2" if (q.option_rank or 1) == 2 else ""),
            "total": str(q.amount), "label": snap.get("package_name") or q.package_key or "Quote",
            "check_in": q.check_in.isoformat() if q.check_in else None, "check_out": q.check_out.isoformat() if q.check_out else None,
            "guests": q.guests, "addons_count": len((snap.get("inputs") or {}).get("addons") or []), "status": q.status,
            "sent": _sent_text(q), "latest": q.id == latest_id, "booked": booked, "usable": usable, "why_not": why,
            "prefill": prefill(q)}


def quotes_for_guest(db: Session, tenant_id: str, guest_id: str, limit: int = 6) -> list[dict]:
    lead_ids = [i for (i,) in db.query(Inquiry.id).filter(Inquiry.tenant_id == tenant_id, Inquiry.guest_id == guest_id).all()]
    if not lead_ids:
        return []
    rows = (db.query(InquiryQuote).filter(InquiryQuote.tenant_id == tenant_id, InquiryQuote.inquiry_id.in_(lead_ids),
                                          InquiryQuote.status.in_(QUOTE_STATUSES))
            .order_by(InquiryQuote.created_at.desc()).limit(limit).all())
    latest = next((r.id for r in rows if r.status == "issued" and (r.option_rank or 1) == 1), None)
    return [quote_card(db, tenant_id, r, latest) for r in rows]


# ─── prefill when opened from somewhere ──────────────────────────────────────────────────────────────────

def context(db: Session, tenant_id: str, *, inquiry_id: Optional[str] = None, guest_id: Optional[str] = None,
            quote_id: Optional[str] = None, packages: Optional[list[dict]] = None, today: Optional[date] = None) -> dict:
    """{"guest": card|None, "lead": lead view|None, "quotes": [...], "quote_id": preselected|None, "trip": {...}}. Raises
    PeopleError (404) for an id that is not this workspace's."""
    stages = qcl._stages(db, tenant_id)
    inq = None
    if quote_id:
        q = db.query(InquiryQuote).filter_by(id=quote_id, tenant_id=tenant_id).first()
        if q is None:
            raise PeopleError("Quote not found.")
        inq = db.query(Inquiry).filter_by(id=q.inquiry_id, tenant_id=tenant_id).first()
    if inquiry_id and inq is None:
        inq = db.query(Inquiry).filter_by(id=inquiry_id, tenant_id=tenant_id).first()
        if inq is None:
            raise PeopleError("Lead not found.")
    gid = inq.guest_id if inq is not None else guest_id
    guest = db.query(Guest).filter_by(id=gid, tenant_id=tenant_id, is_deleted=False).first() if gid else None
    if gid and guest is None:
        raise PeopleError("Guest not found.")
    if guest is None:
        return {"guest": None, "lead": None, "quotes": [], "quote_id": None, "trip": {}}
    lead = inq if inq is not None and qcl.is_open(inq, stages) else open_lead(db, tenant_id, guest.id, stages)
    quotes = quotes_for_guest(db, tenant_id, guest.id)
    pre = quote_id if quote_id and any(c["quote_id"] == quote_id and c["usable"] for c in quotes) else None
    trip: dict = {}
    if lead is not None:
        t = qcl._trip(lead, today or date.today())
        if t.get("start_date"):
            trip["check_in"] = t["start_date"]
            trip["check_out"] = (date.fromisoformat(t["start_date"]) + timedelta(days=t.get("days") or 1)).isoformat()
        if t.get("guests"):
            trip["guests"] = t["guests"]
        key = qcl.match_package(packages or [], t.get("route"))
        if key:
            trip["package_key"] = key
    return {"guest": guest_card(db, tenant_id, guest, stages), "lead": lead_view(lead, stages) if lead is not None else None,
            "quotes": quotes, "quote_id": pre, "trip": trip}
