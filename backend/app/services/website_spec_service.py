"""SiteSpec v2 inside the existing version system (docs/marketing-website/WEBSITE_BUILDER_V2.md).

A v2 site is a SiteVersion whose `doc` is a SiteSpec with "spec_version": 2. No new table: drafts, approval, publish, rollback
and the sha256 integrity check are website_version_service's, which calls validate() here instead of the v1 block cleaner
when it sees a v2 doc. A v1 doc (no spec_version) keeps the v1 path untouched, so existing sites render exactly as before.
"""
from __future__ import annotations

from typing import Optional

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.audit import append_audit
from app.models.tenant import Tenant
from app.models.website import Site, SiteVersion
from app.schemas.site_spec import SiteSpec, _lum, catalogue, derived
from app.services import website_bindings
from app.services.website_service import WebsiteError, site_settings


def is_v2(doc) -> bool:
    return isinstance(doc, dict) and doc.get("spec_version") == 2


def _where(err: dict) -> str:
    return ".".join(str(x) for x in err.get("loc", ()) if not str(x).startswith("function-")) or "spec"


def validate(doc: dict) -> dict:
    """The normalised spec, or WebsiteError 422 spec_invalid listing every problem. Never repairs input."""
    try:
        return SiteSpec.model_validate(doc).model_dump(mode="json")
    except ValidationError as exc:
        problems = [f"{_where(e)}: {e['msg'].removeprefix('Value error, ')}" for e in exc.errors()][:20]
        raise WebsiteError(422, "spec_invalid", "This site plan isn't valid.", problems)


def theme(tokens: dict) -> dict:
    """CSS variables for the renderer. Colour maths lives only here (schemas.site_spec.derived), checked for AA there."""
    cat = catalogue()
    d = derived(tokens["palette"])
    disp, body = cat["fonts"]["display"][tokens["display"]], cat["fonts"]["body"][tokens["body"]]
    r = cat["radius"][tokens["radius"]]
    css = {"--v-ink": d["ink"], "--v-surface": d["surface"], "--v-primary": d["primary"], "--v-accent": d["accent"],
           "--v-muted": d["muted"], "--v-surface-alt": d["surface_alt"], "--v-line": d["line"], "--v-on-primary": d["on_primary"],
           "--v-display": disp["stack"], "--v-body": body["stack"], "--v-display-track": disp["tracking"],
           "--v-display-weight": str(disp["weight"]), "--v-r-card": r["card"], "--v-r-btn": r["button"], "--v-r-media": r["media"]}
    families = sorted({disp["google"], body["google"]})
    return {"vars": css, "motion": tokens["motion"], "scheme": "dark" if _lum(d["surface"]) < 0.2 else "light",
            # shortcut: Google Fonts CSS like the v1 packs; every font in the list is OFL so W5 can self-host them.
            "fonts_href": "https://fonts.googleapis.com/css2?family=" + "&family=".join(families) + "&display=swap"}


def starter(tenant: Tenant, site_block: Optional[dict] = None) -> dict:
    """A complete v2 plan any workspace can start from: copy is generic, everything else binds to HAIP data."""
    prof = (tenant.brand_config or {}).get("business_profile") or {}
    sb = site_block or {}
    contact = {k: str((sb.get("contact") or {}).get(k) or "") for k in ("phone", "whatsapp", "email", "address")}
    if not (contact["phone"] or contact["whatsapp"]):
        contact["phone"] = contact["whatsapp"] = str(prof.get("contact_phone") or "")
    name = (sb.get("name") or tenant.brand_name or tenant.name or "Our stay")[:80]
    home = [
        {"id": "hero", "type": "hero", "variant": "fullbleed-image",
         "slots": {"eyebrow": (prof.get("city") or "")[:60], "headline": (sb.get("tagline") or prof.get("tagline") or name)[:90],
                   "subhead": (prof.get("description") or "")[:240]}},
        {"id": "packages", "type": "packages", "variant": "cards-3", "slots": {"eyebrow": "Journeys", "heading": "Pick your trip"}},
        {"id": "itinerary", "type": "itinerary", "variant": "timeline", "slots": {"eyebrow": "Day by day", "heading": "How a trip unfolds"}},
        {"id": "gallery", "type": "gallery", "variant": "masonry", "slots": {"heading": "On the road"}},
        {"id": "reviews", "type": "reviews", "variant": "quote-carousel", "slots": {"eyebrow": "Guests", "heading": "In their words"}},
        {"id": "faq", "type": "faq", "variant": "accordion", "slots": {"heading": "Good to know"}},
        {"id": "cta", "type": "booking-cta", "variant": "banner",
         "slots": {"heading": "Tell us your dates", "text": "We reply on WhatsApp with a plan for your group."}},
        {"id": "contact", "type": "contact", "variant": "split", "slots": {"heading": "Find us"}},
    ]
    journeys = [
        {"id": "compare", "type": "packages", "variant": "comparison", "slots": {"heading": "Compare journeys"}},
        {"id": "days", "type": "itinerary", "variant": "day-cards", "slots": {"heading": "A sample route"}},
        {"id": "questions", "type": "faq", "variant": "two-column", "slots": {"heading": "Before you book"}},
        {"id": "enquire", "type": "booking-cta", "variant": "inline-form", "slots": {"heading": "Ask for your dates"}},
    ]
    return {
        "spec_version": 2,
        "site": {"name": name, "tagline": (sb.get("tagline") or prof.get("tagline") or "")[:120], "contact": contact,
                 "social": {k: v for k, v in (sb.get("social") or {}).items() if k in ("instagram", "facebook", "youtube")}},
        "tokens": {"palette": "forest-amber", "display": "fraunces", "body": "figtree", "radius": "soft", "motion": "calm"},
        "pages": [
            {"slug": "/", "title": "Home", "nav": False, "seo": {"title": name[:70], "description": (prof.get("description") or "")[:170]},
             "sections": home},
            {"slug": "/journeys", "title": "Journeys", "nav": True, "seo": {"title": f"Journeys · {name}"[:70]}, "sections": journeys},
        ],
    }


def create_draft(db: Session, site: Site, spec: dict, *, actor_id: Optional[str], origin: str = "human",
                 note: Optional[str] = None) -> tuple[SiteVersion, list[str]]:
    """A NEW draft version from a v2 spec (the head draft is kept as history; one in review is withdrawn)."""
    from app.services import website_version_service as vs
    if not is_v2(spec):
        raise WebsiteError(422, "spec_invalid", "This isn't a version 2 site plan.", ["spec_version: must be 2"])
    clean, problems = vs.clean_for_tenant(db, site.tenant_id, spec)
    v = vs.new_draft(db, site, clean, actor_id=actor_id, origin=origin, note=note or "New builder (v2) draft")
    append_audit(db, tenant_id=site.tenant_id, actor_user_id=actor_id, action="website.spec_v2_draft",
                 target_type="site_version", target_id=v.id, payload={"number": v.number, "sha256": v.sha256, "origin": origin})
    return v, problems


def checks(db: Session, site: Site, doc: dict) -> list[dict]:
    """The v2 publish checklist (same shape as website_version_service.checks)."""
    from app.services.invoice_service import get_profile
    tenant = db.get(Tenant, site.tenant_id)
    cfg = site_settings(site)
    out: list[dict] = []

    def add(key: str, ok: bool, title: str, detail: str, level: str = "warn", fix: Optional[str] = None) -> None:
        out.append({"key": key, "ok": ok, "level": "ok" if ok else level, "title": title, "detail": detail, "fix": fix})

    contact = (doc.get("site") or {}).get("contact") or {}
    types = [s["type"] for p in doc.get("pages", []) for s in p["sections"]]
    add("contact_details", bool(contact.get("phone") or contact.get("whatsapp") or contact.get("email")),
        "A phone, WhatsApp or email to reach you", "Shown in the header, footer and contact section.", "block", "site:contact")
    add("contact_section", "contact" in types, "A contact section", "Razorpay and guests look for a way to reach you.", "block")
    paying = cfg.booking_mode in ("instant", "deposit")
    add("policies_page", False, "Policies page", "The new builder adds the policies page in a later phase. Until then keep "
        "booking on request or enquiry." if paying else "Arrives in a later phase; needed before taking payments.",
        "block" if paying else "warn", "settings")
    bad = [p["title"] for p in doc.get("pages", []) if not p["seo"]["title"] or not 50 <= len(p["seo"]["description"]) <= 160]
    add("seo", not bad, "Search previews", "Needs a title and a 50–160 character description: " + ", ".join(bad) if bad
        else "Every page has a title and description.")
    data = website_bindings.resolve(db, tenant, doc)
    empty = sorted({s["type"] for p in doc["pages"] for s in p["sections"] if _is_empty(s["type"], data["bound"].get(s["id"]) or {})})
    add("data", not empty, "Every section has something to show",
        "Hidden until HAIP has data for: " + ", ".join(empty) if empty else "Packages, photos, reviews and FAQs are all in.")
    add("whatsapp", any(v for v in data["page_wa"].values()), "WhatsApp number",
        "WhatsApp buttons carry a reference code so each enquiry can be traced to its section.")
    prof = get_profile(tenant) if tenant else None
    add("legal", bool(prof and prof.legal_name and prof.address), "Legal name and address",
        "Shown in the footer and on invoices (Settings › Invoices).", "warn", "invoice_profile")
    return out


def _is_empty(stype: str, data: dict) -> bool:
    if stype in ("stays", "packages", "reviews", "faq"):
        return not data.get("items")
    if stype == "itinerary":
        return not data.get("itinerary")
    if stype == "gallery":
        return not data.get("media")
    return False


def bootstrap(db: Session, tenant: Tenant, site: Site, version: SiteVersion, *, preview: bool = False) -> dict:
    """What the sites renderer needs for a v2 page: the spec, its bound data, theme variables and photo paths."""
    from app.services import website_public_service as pub
    from app.services.business_data_service import tenant_today
    cfg = site_settings(site)
    doc = version.doc
    data = website_bindings.resolve(db, tenant, doc)
    return {
        "spec_version": 2,
        "site": {"id": site.id, "name": site.name, "status": site.status, "preview": preview, "booking_mode": cfg.booking_mode,
                 "deposit_percent": cfg.deposit_percent, "show_prices": data["price_mode"] == "grounded",
                 "hold_minutes": cfg.hold_minutes, "min_nights": cfg.min_nights, "prices_include_gst": cfg.prices_include_gst,
                 "today": tenant_today(db, tenant.id).isoformat()},
        "version": {"id": version.id, "number": version.number, "sha256": version.sha256},
        "doc": doc,
        "theme": theme(doc["tokens"]),
        "price_mode": data["price_mode"],
        "bound": data["bound"],
        "page_wa": data["page_wa"],
        "assets": pub.asset_urls(db, tenant.id, doc, extra=data["asset_ids"]),
        "legal": pub._legal(tenant),
    }


def media_ids(db: Session, tenant: Tenant, doc: dict) -> set[str]:
    """Photos a v2 page may show: the ones the spec names plus the ones bound to its hero, gallery and stays sections."""
    return website_bindings.resolve(db, tenant, doc, types={"hero", "gallery", "stays"})["asset_ids"]
