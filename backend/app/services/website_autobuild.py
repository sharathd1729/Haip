"""One tap ("Make my website") builds a complete site from what HAIP already knows, with no questions and no empty gaps.

The owner is not a web designer (owner, Oct 2026: "even a first-class student can build it"), so this picks everything:
every section type HAIP has data for (stays, packages, itinerary, photos, reviews, FAQs), always a hero, a booking call to
action and contact; a section with nothing to show is left out rather than shown empty. Copy comes only from the business's
own profile (no invented claims). The result is an ordinary v2 draft (website_spec_service.create_draft): nothing is
public until the owner publishes.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.website import Site
from app.services import website_bindings
from app.services import website_spec_service as wspec

# Sections shown only when HAIP has data for them, in page order (hero first; booking call to action and contact last).
_OPTIONAL = [
    {"id": "stays", "type": "stays", "variant": "cards", "slots": {"eyebrow": "Stay with us", "heading": "Our stays"}},
    {"id": "book", "type": "booking", "variant": "calendar",
     "slots": {"eyebrow": "Book", "heading": "Check dates", "intro": "Pick your dates and send them. We confirm on WhatsApp."}},
    {"id": "packages", "type": "packages", "variant": "cards-3", "slots": {"eyebrow": "Trips", "heading": "Pick your trip"}},
    {"id": "itinerary", "type": "itinerary", "variant": "timeline", "slots": {"eyebrow": "Day by day", "heading": "How a trip unfolds"}},
    {"id": "gallery", "type": "gallery", "variant": "masonry", "slots": {"eyebrow": "Photos", "heading": "Take a look"}},
    {"id": "reviews", "type": "reviews", "variant": "quote-carousel", "slots": {"eyebrow": "Guests", "heading": "What guests say"}},
    {"id": "faq", "type": "faq", "variant": "accordion", "slots": {"heading": "Good to know"}},
]
MIN_GALLERY = 3


def _profile(tenant: Tenant) -> dict:
    """The business profile with any text that states a price blanked: a typed price would fail spec validation."""
    from app.services.price_policy import detect_price
    prof = (tenant.brand_config or {}).get("business_profile") or {}
    return {k: ("" if isinstance(v, str) and detect_price(v) else v) for k, v in prof.items()}


def _seo_description(name: str, prof: dict) -> str:
    text = " ".join(str(prof.get(k) or "").strip() for k in ("tagline", "description")).strip()
    if len(text) < 50:
        text = f"{name}{' in ' + prof['city'] if prof.get('city') else ''}. See our stays and photos, and message us on WhatsApp to book."
    return text[:160].rsplit(" ", 1)[0] if len(text) > 160 else text


def spec_for(db: Session, tenant: Tenant, site_block: Optional[dict] = None) -> dict:
    """The full site plan for this workspace, keeping only the sections HAIP can fill."""
    from app.services.price_policy import detect_price
    base = wspec.starter(tenant, site_block)            # name, contact and social from the existing site / profile
    if detect_price(base["site"]["tagline"]):
        base["site"]["tagline"] = ""
    prof = _profile(tenant)
    name = base["site"]["name"]
    headline = (prof.get("tagline") or base["site"]["tagline"] or name).strip()[:90]
    hero = {"id": "hero", "type": "hero", "variant": "fullbleed-image",
            "slots": {"eyebrow": str(prof.get("city") or "")[:60], "headline": headline,
                      "subhead": str(prof.get("description") or "")[:240], "cta_label": "Check dates"}}
    tail = [
        {"id": "cta", "type": "booking-cta", "variant": "banner",
         "slots": {"heading": "Tell us your dates", "text": "Send your dates and group size on WhatsApp. We reply with what's free.",
                   "cta_label": "Check dates"}},
        {"id": "contact", "type": "contact", "variant": "split", "slots": {"heading": "Find us"}},
    ]
    spec = {**base, "tokens": {"palette": "forest-amber", "display": "bricolage", "body": "figtree", "radius": "soft", "motion": "calm"},
            "pages": [{"slug": "/", "title": "Home", "nav": False,
                       "seo": {"title": name[:70], "description": _seo_description(name, prof)},
                       "sections": [hero, *[dict(s, slots=dict(s["slots"])) for s in _OPTIONAL], *tail]}]}
    bound = website_bindings.resolve(db, tenant, wspec.validate(spec))["bound"]
    keep = []
    for s in spec["pages"][0]["sections"]:
        data = bound.get(s["id"]) or {}
        if s["type"] == "gallery" and len(data.get("media") or []) < MIN_GALLERY:
            continue
        if wspec._is_empty(s["type"], data):
            continue
        keep.append(s)
    spec["pages"][0]["sections"] = keep
    return wspec.validate(spec)


# What to add in HAIP so a section can appear, in plain words, with where to do it (a dashboard path).
_MISSING = {
    "stays": ("Your stays", "Add your caravans, villas or rooms in Properties.", "/dashboard/properties"),
    "booking": ("Check dates", "Appears once you have at least one stay in Properties.", "/dashboard/properties"),
    "packages": ("Trips and packages", "Publish your packages in Knowledge base › Structured business data.", "/dashboard/settings/knowledge"),
    "itinerary": ("Day-by-day route", "Publish an itinerary in Knowledge base › Structured business data.", "/dashboard/settings/knowledge"),
    "gallery": ("Photos", f"Add at least {MIN_GALLERY} photos in Marketing › Studio › Library and approve them.", "/dashboard/marketing/studio"),
    "reviews": ("Guest reviews", "Mark the Google reviews guests agreed to share in Marketing › Studio.", "/dashboard/marketing/studio"),
    "faq": ("Questions and answers", "Approve some questions and answers in the Knowledge base.", "/dashboard/settings/knowledge"),
}


def missing(db: Session, tenant: Tenant) -> list[dict]:
    """Sections HAIP left out because it has no data for them yet, each with what to add and where."""
    have = {s["type"] for s in spec_for(db, tenant)["pages"][0]["sections"]}
    return [{"section": t, "title": title, "how": how, "href": href} for t, (title, how, href) in _MISSING.items() if t not in have]


def make(db: Session, tenant: Tenant, actor_id: Optional[str]) -> tuple[Site, object, list[str]]:
    """Create the site if there is none, then a new draft built from HAIP data. Returns (site, version, problems)."""
    from app.services import website_service as svc
    from app.services import website_version_service as vs
    site = svc.get_site(db, tenant.id) or svc.create_site(db, tenant, actor_id=actor_id)
    head = vs.head(db, site).doc if site.draft_version_id else {}
    block = head.get("site") if isinstance(head, dict) else None
    v, problems = wspec.create_draft(db, site, spec_for(db, tenant, block), actor_id=actor_id, origin="seed",
                                     note="Made by HAIP from your data")
    return site, v, problems
