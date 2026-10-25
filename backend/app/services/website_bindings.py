"""SiteSpec v2 data bindings: what each section shows, read from HAIP at render time (never typed into the spec).

  packages / itinerary  business_data_service.list_effective (PUBLISHED records in effect today only; b2b packages never)
  stays                 bookable properties (website_service.bookable_properties): name, summary, sleeps, amenities and a
                        photo (an approved library photo tagged to the property, else the property's own https photo)
  hero / gallery        approved library photos (marketing_photos.library: active, not AI-pending, no unconsented people)
  reviews               marketing_guest_reviews the owner recorded consent for (consent_at set), 4 stars and up
  faq                   knowledge_entries: category faq, active, approved, not stale, workspace-wide
  contact / cta         the spec's own site.contact

PRICE POLICY (tenant brand_config.price_disclosure, price_policy.price_mode):
  handoff  (default)  no figure anywhere: a package shows "Get the price on WhatsApp" and every bound text that looks like a
                      price (price_policy.detect_price) is dropped before it leaves the server.
  grounded            a package may show ONE figure: package_pricing_service.quote for a stated sample (the package's shortest
                      stay, 2 adults, 14 days out). A refused quote shows no price. Hand-typed figures are dropped in both modes.

WhatsApp: every section gets a wa.me link whose prefilled text ends with a reference code PREFIX-PAGE-SECTION (e.g.
WW-HOME-HERO). The code is deterministic (ref_code) so a later phase can map an inbound message back to the page and section.
"""
from __future__ import annotations

import re
from datetime import timedelta
from typing import Optional
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.models.knowledge import KnowledgeEntry
from app.models.marketing import MarketingGuestReview
from app.models.tenant import Tenant
from app.services import bio_packages
from app.services import business_data_service as bds
from app.services.price_policy import detect_price, price_mode

HANDOFF_LABEL = "Get the price on WhatsApp"
SAMPLE_LEAD_DAYS = 14
SAMPLE_ADULTS = 2


def ref_prefix(spec: dict) -> str:
    given = (spec.get("site") or {}).get("ref_prefix")
    if given:
        return given
    words = re.findall(r"[A-Za-z0-9]+", (spec.get("site") or {}).get("name") or "")
    initials = "".join(w[0] for w in words).upper()[:4]
    return initials if len(initials) >= 2 else ((words[0].upper() if words else "") + "SITE")[:4]


def _token(raw: str, fallback: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (raw or "").upper())[:12] or fallback


def ref_code(prefix: str, slug: str, section_id: str) -> str:
    """PREFIX-PAGE-SECTION, e.g. WW-HOME-HERO, WW-COORG-PACKAGES. Same inputs, same code."""
    page = "HOME" if slug in ("", "/") else _token(slug.rstrip("/").rsplit("/", 1)[-1], "PAGE")
    return f"{prefix}-{page}-{_token(section_id, 'SECTION')}"


def wa_link(number: Optional[str], code: str, about: Optional[str] = None) -> Optional[dict]:
    if not number:
        return None
    text = f"Hi! I'd like to know more about {about}. (Ref {code})" if about else f"Hi! I'd like to know more. (Ref {code})"
    return {"code": code, "href": f"https://wa.me/{number}?text={quote(text)}"}


def _clean(obj):
    """Drop any bound text that states a price (a figure typed into a package summary, an FAQ answer, a review)."""
    if isinstance(obj, str):
        return "" if detect_price(obj) else obj
    if isinstance(obj, list):
        return [x for x in (_clean(v) for v in obj) if x != ""]
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    return obj


class _Ctx:
    """Reads each source at most once per render."""

    def __init__(self, db: Session, tenant: Tenant):
        self.db, self.tenant = db, tenant
        self.today = bds.tenant_today(db, tenant.id)
        self.grounded = price_mode(tenant) == "grounded"
        self._cache: dict = {}

    def once(self, key: str, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    def packages(self) -> list:
        return self.once("packages", lambda: [(r.key, bds.parse(r)) for r in bds.list_effective(self.db, self.tenant.id, "package")
                                              if bds.parse(r).audience != "b2b"])

    def itineraries(self) -> list:
        return self.once("itineraries", lambda: [(r.key, bds.parse(r)) for r in bds.list_effective(self.db, self.tenant.id, "itinerary")])

    def destinations(self) -> dict:
        return self.once("destinations", lambda: {r.key: bds.parse(r) for r in bds.list_effective(self.db, self.tenant.id, "destination")})

    def library(self) -> list:
        from app.services.marketing_photos import library
        return self.once("library", lambda: library(self.db, self.tenant.id))

    def photos(self) -> list[str]:
        return [a.id for a in self.library()]


def _price(ctx: _Ctx, key: str, pkg) -> Optional[dict]:
    """grounded only: the live quote for a stated sample. Never a figure the quote engine did not compute."""
    if not ctx.grounded:
        return None
    from app.services.package_pricing_service import quote
    nights = 0 if pkg.product == "same_day" else max(pkg.min_nights or 0, 1)
    ci = ctx.today + timedelta(days=SAMPLE_LEAD_DAYS)
    adults = min(SAMPLE_ADULTS, pkg.max_guests)
    try:
        q = quote(ctx.db, ctx.tenant.id, key, ci, ci + timedelta(days=nights), adults, as_of=ctx.today)
        if not q.ok and (q.fix or {}).get("nights") is not None:          # e.g. a minimum number of billed days
            nights = int(q.fix["nights"])
            q = quote(ctx.db, ctx.tenant.id, key, ci, ci + timedelta(days=nights), adults, as_of=ctx.today)
    except Exception:  # noqa: BLE001 -- a pricing error hides the figure, never breaks the page
        return None
    if not q.ok or q.total is None:
        return None
    stay = "day trip" if nights == 0 else f"{nights} night{'s' if nights != 1 else ''}"
    return {"amount": str(int(q.total)),
            "label": f"{adults} adult{'s' if adults != 1 else ''}, {stay} from {ci.day} {ci.strftime('%b')}, incl. GST (live quote)"}


def _hero(ctx: _Ctx, s: dict) -> dict:
    media = s["slots"].get("media")
    if not media and ctx.photos():
        media = f"asset:{ctx.photos()[0]}"
    return {"media": media}


def _packages(ctx: _Ctx, s: dict, number: Optional[str], code: str) -> dict:
    pkgs = ctx.packages()
    keys = s["slots"].get("keys") or []
    if keys:
        by = dict(pkgs)
        pkgs = [(k, by[k]) for k in keys if k in by]
    its = ctx.itineraries()
    dests = ctx.destinations()
    items = []
    for key, pkg in pkgs[:6]:
        it = next((i for _, i in its if key in (i.package_keys or [])), None)
        price = _price(ctx, key, pkg)
        items.append({
            "key": key, "name": pkg.name, "summary": _clean(pkg.summary or ""), "length": bio_packages._length(pkg),
            "inclusions": _clean(list(pkg.inclusions or [])[:6]),
            "days": [d.title for d in sorted(it.days, key=lambda d: d.day)] if it else [],
            "destinations": [dests[k].name for k in (pkg.destination_keys or []) if k in dests],
            "max_guests": pkg.max_guests, "price": price,
            "price_label": None if price else HANDOFF_LABEL,
            "wa": wa_link(number, code, pkg.name),
        })
    return {"items": items}


def _itinerary(ctx: _Ctx, s: dict) -> dict:
    its = ctx.itineraries()
    want = s["slots"].get("key")
    found = next((i for k, i in its if k == want), None) if want else (its[0][1] if its else None)
    if not found:
        return {"itinerary": None}
    dest = ctx.destinations().get(found.destination_key)
    names = {k: p.name for k, p in ctx.packages()}
    return {"itinerary": {
        "name": found.name, "nights": found.nights, "destination": dest.name if dest else "",
        "about": _clean(dest.description) if dest else "",
        "packages": [names[k] for k in (found.package_keys or []) if k in names],
        "days": [{"day": d.day, "title": d.title, "stops": list(d.stops), "overnight": d.overnight_location or "",
                  "notes": _clean(d.notes or "")} for d in sorted(found.days, key=lambda d: d.day)],
    }}


def _gallery(ctx: _Ctx, s: dict) -> dict:
    approved = ctx.photos()
    picked = [m for m in s["slots"].get("media") or [] if m.split(":", 1)[1] in set(approved)]
    media = picked or [f"asset:{a}" for a in approved]
    return {"media": media[: s["slots"].get("limit") or 9]}


def _stays(ctx: _Ctx, s: dict) -> dict:
    from app.services.website_public_service import _photos
    from app.services.website_service import bookable_properties
    tagged: dict[str, str] = {}
    for a in ctx.library():
        if a.property_id and a.property_id not in tagged:
            tagged[a.property_id] = f"asset:{a.id}"
    items = []
    for p in bookable_properties(ctx.db, ctx.tenant.id)[: s["slots"].get("limit") or 6]:
        own = _photos(p)
        items.append({"id": p.id, "name": (p.name or "")[:80], "summary": _clean((p.description or "").strip()[:280]),
                      "sleeps": int(p.max_adults or 0) + int(p.max_children or 0), "bedrooms": p.bedrooms,
                      "amenities": [str(a)[:40] for a in (p.amenities or []) if isinstance(a, str)][:6],
                      "photo": tagged.get(p.id) or (own[0] if own else None)})
    return {"items": items}


def _first_name(raw: Optional[str]) -> str:
    return ((raw or "").strip().split() or ["Guest"])[0][:30]


def _reviews(ctx: _Ctx, s: dict) -> dict:
    db, tid = ctx.db, ctx.tenant.id
    rows = (db.query(MarketingGuestReview)
            .filter(MarketingGuestReview.tenant_id == tid, MarketingGuestReview.consent_at.isnot(None),
                    MarketingGuestReview.rating >= 4, MarketingGuestReview.comment.isnot(None))
            .order_by(MarketingGuestReview.reviewed_at.desc()).limit(s["slots"].get("limit") or 6).all())
    rated = [r for (r,) in db.query(MarketingGuestReview.rating).filter(MarketingGuestReview.tenant_id == tid,
                                                                        MarketingGuestReview.rating.isnot(None)).all()]
    items = [{"quote": _clean(r.comment.strip()[:420]), "name": _first_name(r.reviewer), "rating": r.rating,
              "source": r.source, "date": (r.reviewed_at or "")[:7]} for r in rows if r.comment and r.comment.strip()]
    return {"items": [i for i in items if i["quote"]], "count": len(rated),
            "average": round(sum(rated) / len(rated), 1) if rated else None}


def _faq(ctx: _Ctx, s: dict) -> dict:
    rows = (ctx.db.query(KnowledgeEntry)
            .filter(KnowledgeEntry.tenant_id == ctx.tenant.id, KnowledgeEntry.category == "faq",
                    KnowledgeEntry.is_active.is_(True), KnowledgeEntry.review_status == "approved",
                    KnowledgeEntry.stale_since.is_(None), KnowledgeEntry.question.isnot(None),
                    KnowledgeEntry.property_id.is_(None))
            .order_by(KnowledgeEntry.priority.desc(), KnowledgeEntry.created_at).limit(s["slots"].get("limit") or 8).all())
    items = [{"q": _clean(r.question.strip()[:200]), "a": _clean(r.content.strip()[:1200])} for r in rows]
    return {"items": [i for i in items if i["q"] and i["a"]]}


def resolve(db: Session, tenant: Tenant, spec: dict, types: Optional[set[str]] = None) -> dict:
    """{bound: {section_id: data + wa}, page_wa: {slug: wa}, price_mode, asset_ids: set} for a validated spec.
    `types` limits which sections are resolved (the photo route only needs hero and gallery)."""
    ctx = _Ctx(db, tenant)
    number = bio_packages.whatsapp_number(spec, tenant)
    prefix = ref_prefix(spec)
    bound: dict = {}
    page_wa: dict = {}
    for page in spec["pages"]:
        slug = page["slug"]
        page_wa[slug] = wa_link(number, ref_code(prefix, slug, "nav"))
        for s in page["sections"]:
            if types is not None and s["type"] not in types:
                continue
            code = ref_code(prefix, slug, s["id"])
            t = s["type"]
            data = (_hero(ctx, s) if t == "hero" else _stays(ctx, s) if t == "stays" else _packages(ctx, s, number, code) if t == "packages"
                    else _itinerary(ctx, s) if t == "itinerary" else _gallery(ctx, s) if t == "gallery"
                    else _reviews(ctx, s) if t == "reviews" else _faq(ctx, s) if t == "faq" else {})
            data["wa"] = wa_link(number, code)
            bound[s["id"]] = data
    ids: set[str] = set()
    for data in bound.values():
        refs = [i.get("photo") for i in data.get("items") or [] if isinstance(i, dict)]   # stay photos
        for ref in refs + ([data.get("media")] if isinstance(data.get("media"), str) else data.get("media") or []):
            if isinstance(ref, str) and ref.startswith("asset:"):
                ids.add(ref.split(":", 1)[1])
    return {"bound": bound, "page_wa": page_wa, "price_mode": "grounded" if ctx.grounded else "handoff", "asset_ids": ids}
