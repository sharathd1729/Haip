"""Operational facts the AI concierge may rely on when it writes a reply.

The concierge used to know three things about the business: live availability (only when the guest named dates), the knowledge
base, and the vehicle's home city. It did not know what a property actually offers, what the add-ons are, or what the guest has
already booked, so it either asked or guessed. These helpers read that from the same tables the rest of HAIP uses -- there is no
second copy of anything here -- and hand it to the prompt as `grounded_facts`, the one list the reply guards check against.

Rules that hold for every helper:
  * tenant-scoped, and read-only;
  * a guest's bookings are read by the conversation's own guest id and nothing the guest types can select a different guest
    (a booking reference in a message is never looked up);
  * nothing internal: no staff notes, no internal notes, no other guest's data;
  * a missing value is left out, never replaced by a plausible one.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from app.models.property import Property, PropertyAddOn, Stay

log = structlog.get_logger()

# What the guest is told about a booking's state. Stay.status has no "pending": a booking that is confirmed but not yet paid is
# distinguished through payment_status, so the AI cannot call an unpaid booking "fully confirmed and paid".
_BOOKING_WORDS = {
    "confirmed": "confirmed",
    "checked_in": "currently checked in",
    "checked_out": "completed (checked out)",
    "cancelled": "cancelled",
}
_PAYMENT_WORDS = {
    "unpaid": "no payment received yet",
    "partial": "part-paid, balance still due",
    "paid": "fully paid",
}


def valid_stay_dates(check_in: Optional[str], check_out: Optional[str], today: Optional[date] = None) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(check_in, check_out, problem). Dates are kept only if they are real, in order and not in the past.

    A model can return "next weekend" or a date that has already gone by; passing those to the availability lookup raised or
    quoted a stay nobody can book, so they are dropped here and the reply asks for the dates instead.
    """
    today = today or date.today()
    if not check_in or not check_out:
        return None, None, None
    try:
        ci, co = date.fromisoformat(str(check_in)), date.fromisoformat(str(check_out))
    except ValueError:
        return None, None, "not_a_date"
    if co < ci:
        return None, None, "check_out_before_check_in"
    if ci < today:
        return None, None, "in_the_past"
    return ci.isoformat(), co.isoformat(), None


def clean_details(raw: dict, today: Optional[date] = None) -> dict:
    """What the guest actually stated, validated. Unknown or invalid values are left out (never defaulted)."""
    raw = raw or {}
    out: dict = {}
    ci, co, problem = valid_stay_dates(raw.get("check_in"), raw.get("check_out"), today)
    if ci and co:
        out["check_in"], out["check_out"] = ci, co
    elif problem:
        out["date_problem"] = problem
    for key in ("adults", "children"):
        val = raw.get(key)
        if isinstance(val, bool) or not isinstance(val, (int, float)) or val < 0 or val > 100:
            continue
        out[key] = int(val)
    for key in ("destination", "occasion", "property_hint"):
        val = raw.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()[:120]
    budget = raw.get("budget")
    if isinstance(budget, (int, float)) and not isinstance(budget, bool) and budget > 0:
        out["budget"] = int(budget)
    qs = [q.strip()[:140] for q in (raw.get("questions") or []) if isinstance(q, str) and q.strip()][:6]
    if qs:
        out["questions"] = qs
    if raw.get("sentiment") in ("positive", "neutral", "negative", "frustrated"):
        out["sentiment"] = raw["sentiment"]
    if raw.get("urgency") in ("low", "normal", "high"):
        out["urgency"] = raw["urgency"]
    if raw.get("wants_human") is True:
        out["wants_human"] = True
    return out


def property_facts(db: Session, tenant_id: str, property_id: Optional[str] = None, limit: int = 6) -> Optional[dict]:
    """What each active property offers, from the property record. Scoped to one property when the conversation is about one."""
    q = db.query(Property).filter_by(tenant_id=tenant_id, is_active=True)
    if property_id:
        q = q.filter(Property.id == property_id)
    props = q.order_by(Property.name).limit(limit).all()
    if not props:
        return None
    ids = [p.id for p in props]
    addons_by_property: dict[str, list] = {pid: [] for pid in ids}
    for a in (
        db.query(PropertyAddOn)
        .filter(PropertyAddOn.tenant_id == tenant_id, PropertyAddOn.property_id.in_(ids), PropertyAddOn.is_active.is_(True))
        .order_by(PropertyAddOn.sort_order, PropertyAddOn.name)
        .all()
    ):
        if len(addons_by_property[a.property_id]) < 12:
            addons_by_property[a.property_id].append(
                {"name": a.name, "category": a.category, "price": str(a.price), "price_type": a.price_type}
            )

    result = []
    for p in props:
        item: dict = {"property_id": p.id, "name": p.name, "type": p.type}
        for key, val in (
            ("city", p.city), ("home_base", p.home_base), ("vehicle_type", p.vehicle_type),
            ("max_adults", p.max_adults), ("bedrooms", p.bedrooms), ("bathrooms", p.bathrooms),
        ):
            if val:
                item[key] = val
        if p.max_children:
            item["max_children"] = p.max_children
        amenities = [str(a) for a in (p.amenities or []) if a][:25]
        if amenities:
            item["amenities"] = amenities
        if p.description:
            item["description"] = p.description.strip()[:300]
        faqs = []
        for f in (p.faqs or [])[:6]:
            if isinstance(f, dict):
                q_, a_ = f.get("question") or f.get("q"), f.get("answer") or f.get("a")
                if q_ and a_:
                    faqs.append({"question": str(q_)[:160], "answer": str(a_)[:300]})
        if faqs:
            item["faqs"] = faqs
        if addons_by_property[p.id]:
            item["add_ons"] = addons_by_property[p.id]
        result.append(item)
    return {"tool": "property_facts", "scoped_to_one_property": bool(property_id), "result": result}


def guest_booking_facts(db: Session, tenant_id: str, guest_id: str, today: Optional[date] = None) -> Optional[dict]:
    """This guest's own bookings: state, dates, property, party and payment state. No amounts, no internal notes."""
    from app.services import booking_service as bsvc

    today = today or date.today()
    base = db.query(Stay).filter(Stay.tenant_id == tenant_id, Stay.guest_id == guest_id)
    upcoming = base.filter(Stay.check_out >= today).order_by(Stay.check_in.asc()).limit(4).all()
    recent = base.filter(Stay.check_out < today, Stay.check_out >= today - timedelta(days=365)) \
        .order_by(Stay.check_out.desc()).limit(2).all()
    stays = upcoming + recent
    if not stays:
        return None
    try:
        fins = bsvc.financials_for(db, tenant_id, stays)
    except Exception as exc:                                    # a payment lookup problem must not hide the booking itself
        log.warning("concierge_booking_financials_failed", tenant_id=tenant_id, error=str(exc))
        fins = {}
    names = {p.id: p.name for p in db.query(Property).filter(Property.id.in_({s.property_id for s in stays})).all()}

    result = []
    for s in stays:
        status = s.status or "confirmed"
        item = {
            "property_name": names.get(s.property_id, "(property)"),
            "check_in": s.check_in.isoformat() if s.check_in else None,
            "check_out": s.check_out.isoformat() if s.check_out else None,
            "adults": s.adults or 0, "children": s.children or 0,
            "status": status,
            "status_in_words": _BOOKING_WORDS.get(status, status),
        }
        if s.check_in_time:
            item["check_in_time"] = s.check_in_time
        if s.check_out_time:
            item["check_out_time"] = s.check_out_time
        pay = (fins.get(s.id) or {}).get("payment_status")
        if pay and status != "cancelled":
            item["payment_status"] = pay
            item["payment_in_words"] = _PAYMENT_WORDS.get(pay, pay)
        result.append(item)
    return {"tool": "guest_bookings", "scope": "this guest only", "result": result}


def availability_with_reasons(report: list[dict], priced: list) -> list[dict]:
    """Merge the per-property reasons from calculator_service.availability_report() into the priced search results.

    `priced` are the available properties with their rates (search() output rows already turned into dicts). Properties search()
    dropped are added with the reason they were dropped, so "no properties matched" stops meaning four different things.
    """
    have = {p["property_id"] for p in priced}
    out = list(priced)
    for r in report:
        if r["property_id"] in have or r.get("status") == "available":
            continue
        out.append({
            "property_id": r["property_id"], "property_name": r["property_name"], "available": False,
            "reason": r["status"], "max_adults": r.get("max_adults"), "nights": r.get("nights"),
        })
    return out
