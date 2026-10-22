"""The "Packages" list on the link-in-bio page (sites app /links, GET /public/sites/{host}/links): the itinerary funnel.

Only PUBLISHED retail packages in effect today (sales_gateway / business_data_service.list_effective; a partner-only b2b
package never appears), each with its summary, length, the day-by-day titles of its published itinerary, and an "Enquire on
WhatsApp" link whose prefilled text names the package ("Hi! I'd like to know more about Mysuru and Coorg (3 days).") so the
concierge's sales_gateway.match_package ties the enquiry to that package. A price is shown only when the workspace's
price_disclosure is "grounded" ("From Rs 35,000 + GST", the lowest published rate still in effect); in handoff mode, never.
A wa.me link cannot carry utm tags: the package name in the message is the attribution.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.services import business_data_service as bds


def whatsapp_number(site_doc: Optional[dict], tenant) -> Optional[str]:
    """Digits of the business WhatsApp number: the site's contact (whatsapp, else phone), else the marketing profile's phone."""
    contact = ((site_doc or {}).get("site") or {}).get("contact") or {}
    raw = contact.get("whatsapp") or contact.get("phone") or ""
    if not raw:
        prof = ((getattr(tenant, "brand_config", None) or {}).get("business_profile") or {})
        raw = prof.get("contact_phone") or ""
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    return digits if len(digits) >= 10 else None


def _length(pkg) -> str:
    if pkg.product == "same_day" or (pkg.max_nights == 0):
        return "Day trip"
    lo, hi = pkg.min_nights or 1, pkg.max_nights
    if hi is None or hi == lo:
        return f"{lo} night{'s' if lo != 1 else ''} / {lo + 1} days"
    return f"{lo} to {hi} nights"


def _from_price(pkg, today: date) -> Optional[str]:
    amounts = []
    for r in pkg.rates or []:
        try:
            if r.valid_to is None or date.fromisoformat(str(r.valid_to)) >= today:
                amounts.append((Decimal(str(r.amount)), r.unit))
        except (InvalidOperation, ValueError):
            continue
    if not amounts:
        return None
    amount, unit = min(amounts, key=lambda a: a[0])
    figure = _inr(amount)
    per = {"day": " a day", "night": " a night"}.get(str(unit), "")
    return f"From Rs {figure}{per} + GST"


def _inr(amount: Decimal) -> str:
    """Indian grouping: 125000 -> 1,25,000."""
    s = str(int(amount))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail])


def items(db: Session, tenant, site_doc: Optional[dict] = None) -> list[dict]:
    from app.services.price_policy import price_mode
    today = bds.tenant_today(db, tenant.id)
    grounded = price_mode(tenant) == "grounded"
    number = whatsapp_number(site_doc, tenant)
    itineraries = [bds.parse(r) for r in bds.list_effective(db, tenant.id, "itinerary")]
    out = []
    for rec in bds.list_effective(db, tenant.id, "package"):
        pkg = bds.parse(rec)
        if pkg.audience == "b2b":
            continue
        it = next((i for i in itineraries if rec.key in (i.package_keys or [])), None)
        text = f"Hi! I'd like to know more about {pkg.name}."
        out.append({
            "key": rec.key, "name": pkg.name, "summary": pkg.summary, "length": _length(pkg),
            "days": [d.title for d in sorted(it.days, key=lambda d: d.day)] if it else [],
            "price": _from_price(pkg, today) if grounded else None,
            "whatsapp_url": f"https://wa.me/{number}?text={quote(text)}" if number else None,
            "enquiry_text": text,
        })
    return out
