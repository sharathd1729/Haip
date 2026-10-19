"""Who a calculator quote is for: the "Send to" picker, the prefill when the calculator opens from a chat / call / lead / phone
number, and "Add as new lead".

Lead rules (owner decisions):
  * a person with an OPEN lead (stage not Sold/Lost)   -> that lead is used;
  * a person whose leads are all closed (Sold/Lost)    -> a new lead is made for this trip when the quote is saved;
  * an unknown number                                  -> "Add as new lead": the person ONLY via identity_service (an exact
    normalised phone match reuses the guest -- a mirrored WhatsApp chat, an Instagram guest -- never a duplicate), the lead via
    inquiry_service, assigned to the agent. The phone makes them a counted lead (guests.lead_identified_at).
Visibility follows /leads: owner and manager see every lead; other roles their own and unassigned ones. Nothing here calls an LLM.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.pipeline_stage import PipelineStage
from app.models.user import User, UserRole
from app.services import phone_identity

SOURCE_MAP = {"whatsapp": InquirySource.WA_DIRECT, "phone_call": InquirySource.ORGANIC_CALL, "instagram": InquirySource.META_IG,
              "referral": InquirySource.REFERRAL, "walk_in": InquirySource.WALK_IN, "website": InquirySource.WEBSITE, "other": None}
_CLOSED_LEGACY = (InquiryStage.BOOKED, InquiryStage.LOST, InquiryStage.GHOSTED)


class LeadError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def sees_all(user: User) -> bool:
    return user.role in (UserRole.OWNER, UserRole.MANAGER)


def _visible(q, user: User):
    return q if sees_all(user) else q.filter(or_(Inquiry.assigned_to == user.id, Inquiry.assigned_to.is_(None)))


def _stages(db: Session, tenant_id: str) -> dict[str, PipelineStage]:
    return {s.id: s for s in db.query(PipelineStage).filter_by(tenant_id=tenant_id).all()}


def is_open(inq: Inquiry, stages: dict) -> bool:
    st = stages.get(inq.stage_id) if inq.stage_id else None
    if st is not None:
        return not (st.is_closed_won or st.is_closed_lost)
    return inq.stage not in _CLOSED_LEGACY


def _stage_label(inq: Inquiry, stages: dict) -> tuple[str, Optional[str]]:
    st = stages.get(inq.stage_id) if inq.stage_id else None
    if st is not None:
        return st.label, ("won" if st.is_closed_won else "lost" if st.is_closed_lost else st.category)
    return (inq.stage.value.replace("_", " ").title() if inq.stage else "New"), None


def _last4(phone: Optional[str]) -> Optional[str]:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return digits[-4:] if digits and not str(phone).startswith("DELETED_") else None


SOURCE_LABEL = {"wa_direct": "WhatsApp", "click_to_wa": "WhatsApp ad", "meta_ig": "Instagram", "meta_fb": "Facebook",
                "organic_call": "Phone call", "inbound_call": "Phone call", "outbound_call": "Phone call", "phone": "Phone call",
                "referral": "Referral", "walk_in": "Walk-in", "website": "Website", "web_chat": "Website chat"}


def lead_out(inq: Inquiry, guest: Guest, stages: dict) -> dict:
    """One "Send to" row. kind "lead" = an open lead (the quote is saved on it); "new_trip" = a closed lead, so saving makes a
    new lead for this person (guest_id)."""
    label, category = _stage_label(inq, stages)
    open_ = is_open(inq, stages)
    src = inq.source.value if inq.source else None
    return {
        "kind": "lead" if open_ else "new_trip", "inquiry_id": inq.id, "guest_id": guest.id, "guest_name": guest.name or "Unnamed guest",
        "phone_last4": _last4(guest.phone), "source": src, "source_label": SOURCE_LABEL.get(src or "", "Not recorded"),
        "stage_label": label, "stage_category": category, "open": open_, "check_in": inq.check_in, "check_out": inq.check_out,
        "adults": inq.adults, "children": inq.children, "route": inq.route_mentioned,
    }


def search(db: Session, user: User, text: str, limit: int = 20) -> dict:
    """{"results": [lead rows, open leads first], "add": None | {"phone", "known_name"}}. "add" is offered when the text is a
    usable phone number and no visible lead has it."""
    tid = user.tenant_id
    text = (text or "").strip()
    q = _visible(db.query(Inquiry, Guest).join(Guest, Guest.id == Inquiry.guest_id)
                 .filter(Inquiry.tenant_id == tid, Guest.tenant_id == tid, Guest.is_deleted.is_(False)), user)
    digits = "".join(ch for ch in text if ch.isdigit())
    if text:
        conds = [Guest.name.ilike(f"%{text}%")] if not digits or len(digits) < len(text.replace(" ", "")) else []
        if len(digits) >= 4:
            conds.append(Guest.phone.like(f"%{digits[-10:]}%"))
        if not conds:
            return {"results": [], "add": None}
        q = q.filter(or_(*conds))
    stages = _stages(db, tid)
    rows = [lead_out(i, g, stages) for i, g in q.order_by(Inquiry.created_at.desc()).limit(limit * 3).all()]
    rows.sort(key=lambda r: (not r["open"],))
    rows = rows[:limit]
    add = None
    region = phone_identity.region_for_tenant(db, tid)
    e164 = phone_identity.normalize(text, region) if len(digits) >= 10 else None
    if e164 and not rows:
        from app.services.identity_service import find_person_by_phone
        gid = find_person_by_phone(db, tid, e164)
        g = db.query(Guest).filter_by(id=gid, tenant_id=tid).first() if gid else None
        add = {"phone": e164, "known_name": g.name if g else None, "known": g is not None}
    return {"results": rows, "add": add}


def _open_lead_for(db: Session, user: User, guest_id: str, stages: dict) -> tuple[Optional[Inquiry], Optional[Inquiry]]:
    """(the newest open lead of this person, the newest lead of any state)."""
    rows = (db.query(Inquiry).filter(Inquiry.tenant_id == user.tenant_id, Inquiry.guest_id == guest_id)
            .order_by(Inquiry.created_at.desc()).all())
    return next((i for i in rows if is_open(i, stages)), None), (rows[0] if rows else None)


def _can_see(user: User, inq: Inquiry) -> bool:
    return sees_all(user) or inq.assigned_to in (None, user.id)


def create_lead(db: Session, user: User, phone: str, name: Optional[str], source: str) -> dict:
    """"Add as new lead". Returns the lead row (kind "lead"), with "created" and "matched_existing". Commits."""
    from app.services import identity_service, inquiry_service
    tid = user.tenant_id
    region = phone_identity.region_for_tenant(db, tid)
    e164 = phone_identity.normalize(phone, region)
    if not e164:
        raise LeadError("bad_phone", "Enter a full, valid phone number (with the country code if it is not an Indian number).")
    existing = identity_service.find_person_by_phone(db, tid, e164)
    stages = _stages(db, tid)
    if existing:
        open_lead, _ = _open_lead_for(db, user, existing, stages)
        if open_lead is not None:
            if not _can_see(user, open_lead):
                raise LeadError("lead_owned", "This number already has an open lead owned by someone else. Ask them or a manager.", 409)
            guest = db.query(Guest).filter_by(id=existing, tenant_id=tid).first()
            return {**lead_out(open_lead, guest, stages), "created": False, "matched_existing": True}
    guest_id, _created = identity_service.resolve_person_by_phone(db, tid, e164, name=(name or None), source="agent_manual",
                                                                  actor_user_id=user.id)
    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tid).first()
    if name and not guest.name:
        guest.name = name.strip()[:120]
    inq = inquiry_service.create_lead_for_guest(db, tid, guest_id, source=SOURCE_MAP.get(source), has_phone=True,
                                                assigned_to=user.id, commit=True)
    from app.core.audit import append_audit
    append_audit(db, tenant_id=tid, actor_user_id=user.id, action="lead.created_from_quote", target_type="inquiry", target_id=inq.id,
                 payload={"guest_id": guest_id, "matched_existing_person": bool(existing), "source": source})
    db.commit()
    return {**lead_out(inq, guest, stages), "created": True, "matched_existing": bool(existing)}


def new_trip_lead(db: Session, user: User, guest_id: str) -> tuple[Inquiry, bool]:
    """At save time, for a person picked from a closed lead: their open lead if one appeared meanwhile, else a new lead for
    this trip (the previous lead's source, assigned to the agent). (inquiry, created). Flushes; the caller commits."""
    from app.services import inquiry_service
    tid = user.tenant_id
    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tid, is_deleted=False).first()
    if guest is None:
        raise LeadError("not_found", "Guest not found.", 404)
    stages = _stages(db, tid)
    open_lead, last = _open_lead_for(db, user, guest_id, stages)
    if open_lead is not None:
        if not _can_see(user, open_lead):
            raise LeadError("lead_owned", "This guest already has an open lead owned by someone else.", 409)
        return open_lead, False
    if last is not None and not _can_see(user, last):
        raise LeadError("not_found", "Guest not found.", 404)
    inq = inquiry_service.create_lead_for_guest(db, tid, guest_id, source=last.source if last else None,
                                                has_phone=bool(phone_identity.normalize(guest.phone or "")), assigned_to=user.id,
                                                commit=False)
    return inq, True


# ─── prefill (the calculator opened from a chat, a call, a lead or a number) ─────────────────────────────

def _trip(inq: Optional[Inquiry], today: date) -> dict:
    out: dict = {}
    if inq is None:
        return out
    try:
        ci = date.fromisoformat(str(inq.check_in)[:10]) if inq.check_in else None
        co = date.fromisoformat(str(inq.check_out)[:10]) if inq.check_out else None
    except ValueError:
        ci = co = None
    if ci and ci >= today:
        out["start_date"] = ci.isoformat()
        if co and co > ci:
            out["days"] = min((co - ci).days, 30)
    guests = (inq.adults or 0) + (inq.children or 0)
    if guests:
        out["guests"] = guests
    if inq.route_mentioned:
        out["route"] = inq.route_mentioned
    return out


def _call_trip(call, today: date) -> dict:
    """Trip fields the call wrap-up stated (ai_insights.haip_updates: field/value), read defensively."""
    out: dict = {}
    for u in ((call.ai_insights or {}).get("haip_updates") or []) if call is not None else []:
        field, value = str(u.get("field") or "").lower(), str(u.get("value") or "").strip()
        try:
            if field == "check_in" and date.fromisoformat(value[:10]) >= today:
                out["start_date"] = value[:10]
            elif field in ("nights", "days") and value.isdigit():
                out["days"] = max(1, min(int(value), 30))
            elif field in ("adults", "guests", "guest_count") and value.isdigit():
                out["guests"] = max(1, min(int(value), 50))
            elif field in ("route", "destination") and value:
                out["route"] = value[:120]
        except ValueError:
            continue
    return out


def match_package(packages: list[dict], route: Optional[str]) -> Optional[str]:
    r = (route or "").strip().lower()
    if not r:
        return None
    for p in packages:
        name = p["name"].lower()
        if r in name or name.split(" · ")[0] in r:
            return p["key"]
    words = [w for w in r.replace(",", " ").split() if len(w) > 3]
    return next((p["key"] for p in packages if any(w in p["name"].lower() for w in words)), None)


def context(db: Session, user: User, *, inquiry_id=None, guest_id=None, conversation_id=None, call_id=None, phone=None,
            today: date, packages: list[dict]) -> dict:
    """Read-only. {"lead": row|None, "add": {"phone", "known_name"}|None, "trip": {...}, "guest_name", "filled": [...]}"""
    from app.models.call import Call
    from app.models.conversation import Conversation
    tid = user.tenant_id
    stages = _stages(db, tid)
    inq = call = None
    if inquiry_id:
        inq = _visible(db.query(Inquiry).filter(Inquiry.id == inquiry_id, Inquiry.tenant_id == tid), user).first()
        if inq is None:
            raise LeadError("not_found", "Lead not found.", 404)
        guest_id = inq.guest_id
    if conversation_id and inq is None:
        conv = db.query(Conversation).filter_by(id=conversation_id, tenant_id=tid).first()
        if conv is None:
            raise LeadError("not_found", "Conversation not found.", 404)
        guest_id = conv.guest_id
        if conv.inquiry_id:
            inq = db.query(Inquiry).filter_by(id=conv.inquiry_id, tenant_id=tid).first()
    if call_id and inq is None:
        call = db.query(Call).filter_by(id=call_id, tenant_id=tid).first()
        if call is None:
            raise LeadError("not_found", "Call not found.", 404)
        guest_id = guest_id or call.guest_id
        if call.inquiry_id:
            inq = db.query(Inquiry).filter_by(id=call.inquiry_id, tenant_id=tid).first()
        if guest_id is None:
            phone = phone or (call.from_number if str(getattr(call.direction, "value", call.direction)) == "inbound" else call.to_number)
    if guest_id is None and phone:
        from app.services.identity_service import find_person_by_phone
        guest_id = find_person_by_phone(db, tid, phone)
    guest = db.query(Guest).filter_by(id=guest_id, tenant_id=tid, is_deleted=False).first() if guest_id else None
    if guest is not None and (inq is None or not is_open(inq, stages)):
        open_lead, last = _open_lead_for(db, user, guest.id, stages)
        inq = open_lead or inq or last
    if inq is not None and not _can_see(user, inq):
        raise LeadError("not_found", "Lead not found.", 404)
    trip = _trip(inq, today)
    trip.update(_call_trip(call, today))
    key = match_package(packages, trip.get("route"))
    if key:
        trip["package_key"] = key
    filled = [k for k, present in (("route", bool(key)), ("dates", "start_date" in trip), ("guests", "guests" in trip)) if present]
    add = None
    if guest is None and phone:
        e164 = phone_identity.normalize(phone, phone_identity.region_for_tenant(db, tid))
        add = {"phone": e164 or phone, "known_name": None, "known": False}
    elif guest is not None and inq is None:
        add = {"phone": guest.phone, "known_name": guest.name, "known": True}
    return {"lead": lead_out(inq, guest, stages) if inq is not None and guest is not None else None, "add": add, "trip": trip,
            "guest_name": guest.name if guest else None, "filled": filled}

