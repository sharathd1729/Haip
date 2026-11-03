"""One-click launch report (website phase 6): the agency-style handover for a HAIP website, as data (the Launch report
page) and as a PDF. Everything is read from what HAIP already knows; nothing is sent anywhere and no booking is made.

  pages      every page of the LIVE version, its sections and languages (+ per-stay pages, compare, guides)
  quality    website_quality scores (speed / accessibility / search) and what to improve
  schema     the JSON-LD types each page carries (website_seo)
  domain     the site's addresses and their status (free subdomain, custom domain, HTTPS via the sites CDN)
  tracking   Meta Pixel / GA4 / Conversions API settings and the last event HAIP sent (never the token)
  booking    the mode guests get, Razorpay connected, a DRY-RUN price for every stay 30 days out (website_pricing; no hold,
             no link), and the last confirmed website booking
  content    guides live, reviews shown, promo codes on, checklist items still open
"""

from __future__ import annotations

import io
from datetime import timedelta
from xml.sax.saxutils import escape

from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.models.website import BookingHold, Site, SiteVersion, WebsiteEvent, WebsitePromoCode
from app.services import website_bindings, website_quality, website_seo, website_tracking
from app.services import website_public_service as pub
from app.services import website_service as svc
from app.services import website_spec_service as wspec


def _booking(db: Session, tenant: Tenant, site: Site, doc: dict) -> dict:
    from types import SimpleNamespace

    from app.services import website_booking_service as book
    from app.services.business_data_service import tenant_today
    from app.services.payment_link_service import razorpay_credentials

    shown, mode = wspec.guest_terms(tenant, site, doc)
    ci = tenant_today(db, tenant.id) + timedelta(days=30)
    tests = []
    for p in svc.bookable_properties(db, tenant.id, svc.site_settings(site).property_ids or None)[:12]:
        body = SimpleNamespace(
            check_in=ci, check_out=ci + timedelta(days=2), adults=2, children=0, extras=[], promo_code=None
        )
        try:
            q = book.make_quote(db, tenant, site, p, body, mode)
            tests.append(
                {
                    "stay": p.name,
                    "ok": True,
                    "result": f"2 nights from {ci:%d %b}: Rs {q.total:,}"
                    if shown
                    else f"2 nights from {ci:%d %b}: priced (not shown on the site)",
                }
            )
        except svc.WebsiteError as exc:
            tests.append({"stay": p.name, "ok": False, "result": exc.message})
    last = (
        db.query(BookingHold)
        .filter(BookingHold.tenant_id == tenant.id, BookingHold.site_id == site.id, BookingHold.status == "confirmed")
        .order_by(BookingHold.updated_at.desc())
        .first()
    )
    paying = mode in ("instant", "deposit")
    return {
        "mode": mode,
        "prices_shown": shown,
        "razorpay_connected": bool(razorpay_credentials(db, tenant.id)) if paying else None,
        "dry_run": tests,
        "last_booking_at": last.updated_at.isoformat() if last and last.updated_at else None,
    }


def build(db: Session, tenant: Tenant, site: Site) -> dict:
    from app.services import website_blog, website_reviews

    live = db.get(SiteVersion, site.live_version_id) if site.live_version_id else None
    out: dict = {
        "site": {"name": site.name, "status": site.status, "url": f"https://{svc.primary_host(db, site)}"},
        "published": None,
    }
    if live is None:
        out["problem"] = "This website isn't published yet. Publish it, then make the launch report."
        return out
    doc = live.doc
    out["published"] = {"version": live.number, "at": live.published_at.isoformat() if live.published_at else None}
    host = svc.primary_host(db, site)
    out["domain"] = [
        {"host": d.hostname, "kind": d.kind, "status": d.status, "https": d.status in ("active", "verified")}
        for d in svc.domains(db, site)
    ]
    if not wspec.is_v2(doc):
        out["problem"] = 'This is a classic website. Tap "Make my website" for the full launch report.'
        return out
    data = website_bindings.resolve(db, tenant, doc, site=site)
    assets = pub.asset_urls(db, tenant.id, doc, extra=data["asset_ids"])
    stays = website_bindings.stay_index(db, tenant, site)
    langs = sorted((doc.get("i18n") or {}).keys())
    out["pages"] = [
        {
            "title": p["title"],
            "path": p["slug"],
            "sections": [s["type"] for s in p["sections"]],
            "languages": ["en", *langs],
        }
        for p in doc["pages"]
    ]
    out["extra_pages"] = (
        [f"/stays/{s['slug']}" for s in stays]
        + (["/compare"] if len(stays) > 1 else [])
        + (["/blog"] if website_blog.listing(db, tenant.id) else [])
        + ["/policies", "/my-booking"]
    )
    q = website_quality.audit(doc, data["bound"], assets)
    out["quality"] = {
        "scores": q["scores"],
        "to_improve": [i["title"] + ": " + i["detail"] for i in q["items"] if not i["ok"]],
    }
    ld = website_seo.jsonld(tenant, doc, data["bound"], assets, host=host, grounded=data["price_mode"] == "grounded")
    out["schema"] = {slug: [x["@type"] for x in items] for slug, items in ld.items()}
    t = website_tracking.settings_out(site)
    last = (
        db.query(WebsiteEvent)
        .filter_by(tenant_id=tenant.id, site_id=site.id, status="sent")
        .order_by(WebsiteEvent.sent_at.desc())
        .first()
    )
    out["tracking"] = {
        "meta_pixel": bool(t["pixel_id"]),
        "ga4": bool(t["ga4_id"]),
        "conversions_api": website_tracking.capi_on(site),
        "cookie_banner": bool(t["pixel_id"] or t["ga4_id"]),
        "last_event_sent_at": last.sent_at.isoformat() if last and last.sent_at else None,
    }
    out["booking"] = _booking(db, tenant, site, doc)
    out["content"] = {
        "guides_live": len(website_blog.listing(db, tenant.id)),
        "reviews_shown": sum(1 for r in website_reviews.listing(db, tenant.id) if r["shown"]),
        "promo_codes_on": db.query(WebsitePromoCode).filter_by(tenant_id=tenant.id, active=True).count(),
        "languages": ["English", *[website_seo_lang(x) for x in langs]],
        "get_found": _get_found(db, tenant),
    }
    out["open_items"] = [c["title"] for c in wspec.checks(db, site, doc) if not c["ok"]]
    return out


def _get_found(db: Session, tenant: Tenant) -> dict:
    """Steps done across the Get found checklists (services/sops): Google profile, Instagram, WhatsApp."""
    from app.services.sops import service as sops

    rows = sops.list_view(db, tenant)["instances"]
    return {"done": sum(r["done"] for r in rows), "total": sum(r["total"] for r in rows), "checklists": len(rows)}


def website_seo_lang(code: str) -> str:
    from app.schemas.site_spec import LANGUAGES

    return {"hi": "Hindi"}.get(code, LANGUAGES.get(code, code))


def _latin(text) -> str:
    """reportlab's built-in Helvetica is Latin-1 only (Hindi words are not printed; their language is named instead)."""
    return escape(str(text).replace("₹", "Rs ").encode("latin-1", "replace").decode("latin-1"))


def render(report: dict, *, brand: str | None = None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()
    h1, h2, body = ss["Title"], ss["Heading2"], ss["BodyText"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Website launch report",
    )
    el = [
        Paragraph(_latin(f"Website launch report: {report['site']['name']}"), h1),
        Paragraph(_latin(f"{report['site']['url']} · {report['site']['status']}"), body),
    ]

    def table(rows):
        t = Table([[Paragraph(_latin(c), body) for c in r] for r in rows], colWidths=[60 * mm, 118 * mm])
        t.setStyle(
            TableStyle(
                [("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#D9DED9")), ("VALIGN", (0, 0), (-1, -1), "TOP")]
            )
        )
        return t

    def section(title, rows):
        el.extend(
            [
                Spacer(1, 4 * mm),
                Paragraph(_latin(title), h2),
                table(rows) if rows else Paragraph("Nothing to show.", body),
            ]
        )

    if report.get("problem"):
        el.append(Paragraph(_latin(report["problem"]), body))
    if report.get("published"):
        section("Published", [["Version", report["published"]["version"]], ["When", report["published"]["at"] or "-"]])
    if report.get("domain"):
        section(
            "Domain",
            [[d["host"], f"{d['kind']}, {d['status']}{', HTTPS' if d['https'] else ''}"] for d in report["domain"]],
        )
    if report.get("pages"):
        section(
            "Pages",
            [[p["path"], f"{p['title']}: {', '.join(p['sections'])}"] for p in report["pages"]]
            + [["Also", ", ".join(report.get("extra_pages") or [])]],
        )
    if report.get("quality"):
        s = report["quality"]["scores"]
        section(
            "Speed, accessibility, search",
            [
                [
                    "Scores",
                    f"Speed {s['performance']}, accessibility {s['accessibility']}, search {s['seo']} (out of 100)",
                ]
            ]
            + [["To improve", x] for x in report["quality"]["to_improve"]],
        )
    if report.get("schema"):
        section("Google structured data", [[k, ", ".join(v)] for k, v in report["schema"].items()])
    if report.get("tracking"):
        t = report["tracking"]
        section(
            "Tracking",
            [
                ["Meta Pixel", "on" if t["meta_pixel"] else "off"],
                ["Google Analytics 4", "on" if t["ga4"] else "off"],
                ["Conversions API", "on" if t["conversions_api"] else "off"],
                ["Cookie banner", "shown" if t["cookie_banner"] else "not needed"],
                ["Last event sent", t["last_event_sent_at"] or "-"],
            ],
        )
    if report.get("booking"):
        b = report["booking"]
        section(
            "Booking test (dry run, nothing booked)",
            [
                ["Guests can", b["mode"]],
                ["Prices shown", "yes" if b["prices_shown"] else "no"],
                [
                    "Razorpay",
                    "-"
                    if b["razorpay_connected"] is None
                    else ("connected" if b["razorpay_connected"] else "NOT connected"),
                ],
                ["Last website booking", b["last_booking_at"] or "-"],
            ]
            + [[x["stay"], ("OK: " if x["ok"] else "Problem: ") + x["result"]] for x in b["dry_run"]],
        )
    if report.get("content"):
        c = report["content"]
        section(
            "Content",
            [
                ["Guides live", c["guides_live"]],
                ["Reviews shown", c["reviews_shown"]],
                ["Promo codes on", c["promo_codes_on"]],
                ["Languages", ", ".join(c["languages"])],
                ["Get found steps done", f"{c['get_found']['done']} of {c['get_found']['total']}"
                 if c.get("get_found", {}).get("checklists") else "No checklist started"],
            ],
        )
    if report.get("open_items"):
        section("Still to do", [["-", x] for x in report["open_items"]])
    el.append(Spacer(1, 6 * mm))
    el.append(Paragraph(_latin(f"Made by HAIP{' for ' + brand if brand else ''}."), body))
    doc.build(el)
    return buf.getvalue()
