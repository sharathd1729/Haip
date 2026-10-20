"""What the guest wants to buy, assembled for the AI sales agent -- with no extraction of its own.

It combines two things that already exist: what the concierge's message understanding found in this conversation (`details`:
dates, party, destination, the questions asked) and what the lead already records (Inquiry.check_in/check_out/adults/children/
route_mentioned). A value stated in the conversation wins; otherwise the lead's. Dates go through the same validation the
concierge uses (concierge_facts.valid_stay_dates: real, in order, not past).

The plan (package) and route (destination) are matched against PUBLISHED records only (sales_gateway / business_data_service).
Anything the agent must not handle on its own becomes a `handoff` reason instead of a guess:

  b2b              a travel agent / reseller / corporate enquiry (reseller terms are staff work)
  discount_request the guest asks for a discount or a better price (only staff apply the published discount policy)
  custom_route     the guest named a place that is not a published route and no plan covers it
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from app.services import business_data_service as bds
from app.services import concierge_facts, sales_gateway

_B2B_RE = re.compile(r"\b(travel agen(?:t|cy|ts)|tour operator|reseller|b2b|commission|corporate (?:booking|offsite|group)|"
                     r"for (?:my|our) (?:clients|customers)|agency)\b", re.IGNORECASE)
_DISCOUNT_RE = re.compile(r"\b(discount|cheaper|best (?:price|rate|deal)|lower (?:the )?(?:price|rate)|reduce (?:the )?(?:price|rate)|"
                          r"any offers?|negotiat\w*|bargain|coupon|promo(?:tion)? code)\b", re.IGNORECASE)
_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall((text or "").lower()))


@dataclass
class Requirement:
    check_in: Optional[date] = None
    check_out: Optional[date] = None
    adults: Optional[int] = None
    children: int = 0
    package_key: Optional[str] = None
    destination_key: Optional[str] = None
    phone_ok: bool = False
    missing: list[str] = field(default_factory=list)
    handoff: Optional[str] = None

    @property
    def complete(self) -> bool:
        return not self.missing and self.handoff is None

    def key(self) -> str:
        """Same plan, route, dates and party -> same key. A changed requirement is what allows a new quote within 24 hours."""
        blob = json.dumps([self.package_key, self.destination_key, self.check_in and self.check_in.isoformat(),
                           self.check_out and self.check_out.isoformat(), self.adults, self.children])
        return hashlib.sha256(blob.encode()).hexdigest()

    def as_fact(self) -> dict:
        return {"check_in": self.check_in.isoformat() if self.check_in else None,
                "check_out": self.check_out.isoformat() if self.check_out else None, "adults": self.adults,
                "children": self.children, "package_key": self.package_key, "destination_key": self.destination_key,
                "missing": list(self.missing)}


def _hint(details: dict, inquiry) -> str:
    """What the guest said in this conversation; the lead's recorded route only when the conversation names none."""
    parts = [str(details.get(k) or "") for k in ("destination", "property_hint")]
    parts.append(" ".join(details.get("questions") or []))
    said = " ".join(p for p in parts if p)
    return said if (details.get("destination") or details.get("property_hint")) else         " ".join(p for p in (said, getattr(inquiry, "route_mentioned", None) or "") if p)


def _destination_hits(db: Session, tenant_id: str, hint: str) -> list[str]:
    words = _tokens(hint)
    if not words:
        return []
    hits = []
    for rec in bds.list_effective(db, tenant_id, "destination"):
        name = _tokens(bds.parse(rec).name)
        key = _tokens(rec.key.replace("-", " "))
        first = next(iter(_WORD.findall(bds.parse(rec).name.lower())), None)   # "Coorg" names "Coorg, stay in Virajpet"
        if (name and name <= words) or (key and key <= words) or (first and first in words):
            hits.append(rec.key)
    return sorted(set(hits))


def match_destination(db: Session, tenant_id: str, hint: str) -> Optional[str]:
    """The ONE published destination named in the hint (by name or key), else None (none, or two that fit)."""
    hits = _destination_hits(db, tenant_id, hint)
    return hits[0] if len(hits) == 1 else None


def assemble(db: Session, tenant_id: str, inquiry, guest, details: Optional[dict], text: str = "") -> Requirement:
    details = details or {}
    req = Requirement()
    ci, co = details.get("check_in"), details.get("check_out")
    if not (ci and co) and inquiry is not None:
        ci, co, _ = concierge_facts.valid_stay_dates(inquiry.check_in, inquiry.check_out, bds.tenant_today(db, tenant_id))
    if ci and co:
        req.check_in, req.check_out = date.fromisoformat(ci), date.fromisoformat(co)
    req.adults = details.get("adults") or (getattr(inquiry, "adults", None) if inquiry is not None else None) or None
    req.children = int(details.get("children") or (getattr(inquiry, "children", None) if inquiry is not None else 0) or 0)

    hint = _hint(details, inquiry)
    req.package_key = sales_gateway.match_package(db, tenant_id, {**details, "destination": hint})
    req.destination_key = match_destination(db, tenant_id, hint)
    if req.package_key is None and req.destination_key:
        # The guest named a route, not a plan: the plan is the ONE published package made for that route (a plan open to every
        # route is not a choice the agent makes for the guest).
        own = [r.key for r in bds.list_effective(db, tenant_id, "package") if req.destination_key in bds.parse(r).destination_keys]
        req.package_key = own[0] if len(own) == 1 else None
    if req.package_key:
        pkg = bds.parse(bds.get_effective(db, tenant_id, "package", req.package_key))
        if pkg.destination_keys and req.destination_key is None and len(pkg.destination_keys) == 1:
            req.destination_key = pkg.destination_keys[0]

    from app.services.quote_send_service import usable_phone
    req.phone_ok = usable_phone(guest)

    if _B2B_RE.search(text or ""):
        req.handoff = "b2b"
    elif _DISCOUNT_RE.search(text or ""):
        req.handoff = "discount_request"
    elif details.get("destination") and not req.package_key and not _destination_hits(db, tenant_id, hint):
        req.handoff = "custom_route"            # a place that is no published route at all (two that fit = ask which)

    if not (req.check_in and req.check_out):
        req.missing.append("travel dates")
    if not req.adults:
        req.missing.append("number of guests")
    if not req.package_key:
        req.missing.append("which plan or route")
    if not req.phone_ok:
        req.missing.append("a WhatsApp number to send the quote to")
    return req


def price(db: Session, tenant_id: str, req: Requirement):
    """(GatewayResult, PackageQuote) for the requirement, from published records only. Never a discount, never a level guess."""
    return sales_gateway.quote_package_detailed(db, tenant_id, req.package_key, req.check_in, req.check_out, int(req.adults),
                                                int(req.children or 0), destination_key=req.destination_key)


def fallback_plan(db: Session, tenant_id: str, req: Requirement, primary_key: str):
    """Another published plan that also prices for this route, dates and party (lowest total), or None. Offered as option 2."""
    best = None
    for rec in bds.list_effective(db, tenant_id, "package"):
        if rec.key == primary_key:
            continue
        pkg = bds.parse(rec)
        dest = req.destination_key if (req.destination_key and (not pkg.destination_keys or req.destination_key in pkg.destination_keys)) else None
        if pkg.destination_keys and dest is None:
            continue
        _, q = sales_gateway.quote_package_detailed(db, tenant_id, rec.key, req.check_in, req.check_out, int(req.adults),
                                                    int(req.children or 0), destination_key=dest)
        if q.ok and not q.uses_drafts and (best is None or q.total < best.total):
            best = q
    return best
