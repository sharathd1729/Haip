"""Promo codes for website bookings (website phase 4, migration 184).

Owner/manager create and change them (Website page › Promo codes); every change is audited (`website.promo_*`). A guest
types a code at checkout: `check()` decides it on the server (active, inside its dates by the check-in day, enough
nights, this stay allowed, uses left counting other guests' live holds) and website_pricing.quote applies it to the
nights' rates, so GST is charged on what the guest really pays and the Razorpay amount follows. A paid booking counts a
use (`count_use`, guarded UPDATE; a booking that slipped past the cap is still honoured and audited). On a handoff-price
site the code still travels with the request (the team honours it), but no amount is shown to the guest.
"""
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.website import BookingHold, WebsitePromoCode
from app.services.website_service import WebsiteError


def _norm(code: Optional[str]) -> str:
    return (code or "").strip().upper()


def out(p: WebsitePromoCode) -> dict:
    return {"id": p.id, "code": p.code, "kind": p.kind, "value": float(p.value), "starts_on": p.starts_on, "ends_on": p.ends_on,
            "min_nights": p.min_nights, "max_uses": p.max_uses, "used_count": p.used_count,
            "property_ids": p.property_ids or [], "label": p.label, "active": p.active}


def list_codes(db: Session, tenant_id: str) -> list[WebsitePromoCode]:
    return db.query(WebsitePromoCode).filter_by(tenant_id=tenant_id).order_by(WebsitePromoCode.created_at.desc()).all()


def _fields(body) -> dict:
    return {"code": _norm(body.code), "kind": body.kind, "value": Decimal(str(body.value)), "starts_on": body.starts_on,
            "ends_on": body.ends_on, "min_nights": body.min_nights, "max_uses": body.max_uses,
            "property_ids": list(dict.fromkeys(body.property_ids)), "label": body.label, "active": body.active}


def _known_properties(db: Session, tenant_id: str, ids: list[str]) -> None:
    from app.services.website_service import bookable_properties
    unknown = set(ids) - {p.id for p in bookable_properties(db, tenant_id)}
    if unknown:
        raise WebsiteError(422, "unknown_property", "Some selected stays are not active properties.", sorted(unknown))


def create(db: Session, tenant_id: str, body, *, actor_id: str) -> WebsitePromoCode:
    f = _fields(body)
    _known_properties(db, tenant_id, f["property_ids"])
    if db.query(WebsitePromoCode.id).filter_by(tenant_id=tenant_id, code=f["code"]).first():
        raise WebsiteError(409, "code_exists", f"There is already a code {f['code']}.")
    p = WebsitePromoCode(tenant_id=tenant_id, created_by=actor_id, **f)
    db.add(p)
    db.flush()
    append_audit(db, tenant_id=tenant_id, actor_user_id=actor_id, action="website.promo_created", target_type="website_promo",
                 target_id=p.id, payload={k: (str(v) if isinstance(v, (Decimal, date)) else v) for k, v in f.items()})
    return p


def update(db: Session, tenant_id: str, promo_id: str, body, *, actor_id: str) -> WebsitePromoCode:
    p = db.query(WebsitePromoCode).filter_by(id=promo_id, tenant_id=tenant_id).first()
    if p is None:
        raise WebsiteError(404, "not_found", "No such promo code.")
    f = _fields(body)
    _known_properties(db, tenant_id, f["property_ids"])
    if f["code"] != p.code and db.query(WebsitePromoCode.id).filter_by(tenant_id=tenant_id, code=f["code"]).first():
        raise WebsiteError(409, "code_exists", f"There is already a code {f['code']}.")
    before = out(p)
    for k, v in f.items():
        setattr(p, k, v)
    db.flush()
    after = out(p)
    append_audit(db, tenant_id=tenant_id, actor_user_id=actor_id, action="website.promo_changed", target_type="website_promo",
                 target_id=p.id, payload={"changed": {k: [str(before[k]), str(v)] for k, v in after.items() if before[k] != v}})
    return p


def _live_holds_using(db: Session, tenant_id: str, code: str) -> int:
    rows = db.query(BookingHold.quote).filter(BookingHold.tenant_id == tenant_id,
                                              BookingHold.status.in_(("held", "confirming"))).limit(500).all()
    return sum(1 for (q,) in rows if (q or {}).get("promo_code") == code)


def check(db: Session, tenant_id: str, code: Optional[str], *, property_id: str, check_in: date, nights: int,
          for_hold: bool = False) -> Optional[WebsitePromoCode]:
    """The promo to apply, None for no code, or WebsiteError 422 promo_invalid in words a guest understands."""
    c = _norm(code)
    if not c:
        return None
    p = db.query(WebsitePromoCode).filter_by(tenant_id=tenant_id, code=c).first()

    def no(msg: str):
        raise WebsiteError(422, "promo_invalid", msg)
    if p is None or not p.active:
        no("That code isn't valid. Check the spelling.")
    if p.starts_on and check_in < p.starts_on or p.ends_on and check_in > p.ends_on:
        no("That code isn't valid for these dates.")
    if nights < (p.min_nights or 1):
        no(f"That code needs a stay of at least {p.min_nights} nights.")
    if p.property_ids and property_id not in p.property_ids:
        no("That code isn't valid for this stay.")
    if p.max_uses is not None and p.used_count + (_live_holds_using(db, tenant_id, c) if for_hold else 0) >= p.max_uses:
        no("That code has been used up.")
    return p


def label(p: WebsitePromoCode) -> str:
    return f"{float(p.value):g}% off" if p.kind == "percent" else f"₹{float(p.value):,.0f} off"


def count_use(db: Session, tenant_id: str, hold: BookingHold) -> None:
    """A paid booking used its code: +1, guarded by the cap. Over the cap = still honoured (the guest paid), audited."""
    c = (hold.quote or {}).get("promo_code")
    if not c:
        return
    q = db.query(WebsitePromoCode).filter(WebsitePromoCode.tenant_id == tenant_id, WebsitePromoCode.code == c)
    n = q.filter((WebsitePromoCode.max_uses.is_(None)) | (WebsitePromoCode.used_count < WebsitePromoCode.max_uses)).update(
        {"used_count": WebsitePromoCode.used_count + 1}, synchronize_session=False)
    if n == 0:
        q.update({"used_count": WebsitePromoCode.used_count + 1}, synchronize_session=False)
    append_audit(db, tenant_id=tenant_id, action="website.promo_used", target_type="booking_hold", target_id=hold.id,
                 payload={"actor": "system", "code": c, "discount": (hold.quote or {}).get("discount"), "over_cap": n == 0})


def banner(db: Session, tenant_id: str, code: Optional[str], *, today: date, grounded: bool) -> Optional[dict]:
    """What an offer banner may say about its code: nothing if it isn't usable now; the amount only in grounded mode."""
    p = db.query(WebsitePromoCode).filter_by(tenant_id=tenant_id, code=_norm(code)).first() if code else None
    if p is None or not p.active or (p.ends_on and p.ends_on < today) or (p.max_uses is not None and p.used_count >= p.max_uses):
        return None
    return {"code": p.code, "until": p.ends_on.isoformat() if p.ends_on else None, "min_nights": p.min_nights,
            "label": label(p) if grounded else None}
