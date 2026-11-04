"""Inputs and slot fills for the phase S2 SOPs (OTA listings + promotions, catalogue_ota.py), all from the shared layer:

ota_copy        the Studio's latest READY OTA copy draft for this property + platform (marketing_ota_copies)
house_rules     the published stay rules (sales_gateway.policy_check "stay_rules")
ical            HAIP's calendar export link for this property (ical_feeds)
season          long weekends + public holidays in the next 90 days (marketing_demand, the workspace's state)
free_dates      this property's open nights in the next 60 days (marketing_demand.free_nights)
programmes      programme names from the platform rules catalogue only
discount_policy the published discount policy (sales_gateway): owner/manager only, flagged `restricted`
packages        published retail packages (sales_gateway.list_packages: never b2b), names and length only
offer_text      the AI's short offer name (generate.py), never a figure
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.models.ical_feed import ICalFeed
from app.models.marketing_partners import MarketingOtaCopy
from app.models.property import Property
from app.models.sop import SopInstance
from app.models.tenant import Tenant
from app.services.sops import rules

SLOTS = (
    "ota_copy",
    "house_rules",
    "ical",
    "season",
    "free_dates",
    "programmes",
    "discount_policy",
    "packages",
    "offer_text",
)
VOLATILE = ("season", "free_dates")  # change every day: not part of inputs_sha (a new version only when facts change)
# how a person names this platform's calendar link in HAIP (ical_feeds.name), for the "calendar both ways" check
FEED_WORDS = {
    "airbnb": ("airbnb",),
    "booking": ("booking",),
    "makemytrip": ("makemytrip", "mmt", "goibibo"),
    "agoda": ("agoda",),
}
COPY_LABELS = {
    "the_space": "The space",
    "guest_access": "Guest access",
    "getting_around": "Getting around",
    "house_rules": "House rules",
}
BUSINESS_DATA = "/dashboard/settings/knowledge"


def matching_feed(feeds: list[ICalFeed], platform: str) -> ICalFeed | None:
    words = FEED_WORDS.get(platform, ())
    return next((f for f in feeds if f.import_url_enc and any(w in (f.name or "").lower() for w in words)), None)


def collect(db: Session, tenant: Tenant, inst: SopInstance, platform: str, slots: set[str]) -> dict:
    from app.core.config import settings
    from app.services import booking_agenda_service, marketing_demand, sales_gateway

    out: dict = {}
    if "ota_copy" in slots:
        row = (
            db.query(MarketingOtaCopy)
            .filter_by(tenant_id=tenant.id, property_id=inst.property_id, platform=platform, status="ready")
            .order_by(MarketingOtaCopy.created_at.desc())
            .first()
        )
        out["ota_copy"] = ((row.body or {}).get("copy") or None) if row else None
    if "house_rules" in slots:
        r = sales_gateway.policy_check(db, tenant.id, "stay_rules")
        out["house_rules"] = r.data if r.ok else None
    if "discount_policy" in slots:
        r = sales_gateway.policy_check(db, tenant.id, "discount")
        out["discount_policy"] = r.data if r.ok else None
    if "packages" in slots:
        r = sales_gateway.list_packages(db, tenant.id)
        out["packages"] = (
            [{"name": p["name"], "min_nights": p["min_nights"], "max_nights": p["max_nights"]} for p in (r.data or [])]
            if r.ok
            else []
        )
    if "ical" in slots:
        feeds = db.query(ICalFeed).filter_by(tenant_id=tenant.id, property_id=inst.property_id, is_active=True).all()
        base = (settings.API_BASE_URL or "").rstrip("/")
        out["ical"] = (
            f"{base}/api/v1/ical/{feeds[0].export_token}.ics" if feeds and base.startswith("https://") else None
        )
    if slots & {"season", "free_dates"}:
        today = booking_agenda_service.tenant_today(db, tenant.id)
        state = marketing_demand.home_state(db, tenant)
        if "season" in slots:
            out["season"] = {
                "long_weekends": marketing_demand.long_weekends(state, today, today + timedelta(days=90)),
                "holidays": [
                    o
                    for o in marketing_demand.occasions(state, today, today + timedelta(days=90))
                    if o["kind"] == "public"
                ],
            }
        if "free_dates" in slots:
            prop = db.get(Property, inst.property_id) if inst.property_id else None
            free = marketing_demand.free_nights(db, tenant.id, today, today + timedelta(days=60))
            out["free_dates"] = [d.isoformat() for d in free.get(prop.name, [])] if prop else []
    return out


def fill(slot: str, platform: str, inp: dict, text: dict, step: dict) -> None:
    values, needs = step["values"], step["needs"]
    if slot == "ota_copy":
        copy = inp.get("ota_copy")
        if not copy:
            needs.append(
                {
                    "label": "Draft this listing's text in Marketing Studio (Partners)",
                    "href": "/dashboard/marketing/studio?tab=partners",
                }
            )
        for k, v in (copy or {}).items():
            label = COPY_LABELS.get(k, k.replace("_", " ").capitalize())
            if isinstance(v, list):
                values.extend({"label": f"{label} {i + 1}", "text": x} for i, x in enumerate(v) if x)
            elif v:
                values.append({"label": label, "text": v})
    elif slot == "house_rules":
        r = inp.get("house_rules")
        if not r:
            needs.append({"label": "Publish your stay rules (check-in time, house rules)", "href": BUSINESS_DATA})
        else:
            values.append({"label": "Check-in / check-out", "text": f"{r['check_in_time']} / {r['check_out_time']}"})
            if r.get("house_rules"):
                values.append({"label": "House rules", "text": "\n".join(r["house_rules"])})
    elif slot == "ical":
        if inp.get("ical"):
            values.append({"label": "HAIP calendar link", "text": inp["ical"]})
        else:
            needs.append({"label": "Set up this property's calendar link", "href": "/dashboard/settings/calendar-sync"})
    elif slot == "season":
        s = inp.get("season") or {}
        lines = [
            f"{w['start']} to {w['end']} ({w['days']} days){': ' + w['reason'] if w['reason'] else ''}"
            for w in s.get("long_weekends", [])
        ]
        lines += [f"{h['date']} {h['name']}" for h in s.get("holidays", [])]
        values.append({"label": "Coming up", "text": "\n".join(lines)} if lines else None)
        if not lines:
            step["notes"].append("No long weekends or public holidays in the next 90 days.")
    elif slot == "free_dates":
        free = inp.get("free_dates") or []
        values.append(
            {
                "label": "Free nights, next 60 days",
                "text": f"{len(free)} nights" + (f", first {', '.join(free[:6])}" if free else ""),
            }
        )
    elif slot == "programmes":
        names = [
            rules.ref(e) | {"name": e.value}
            for e in rules.all_rules().values()
            if e.platform == platform and e.kind == "programme"
        ]
        step["categories"] = names or None
        if not names:
            step["notes"].append(
                f"HAIP has no programme list for this platform yet: {rules.CHECK_IN_PLATFORM.lower()}."
            )
    elif slot == "discount_policy":
        d = inp.get("discount_policy")
        if not d:
            needs.append({"label": "Publish your discount policy", "href": BUSINESS_DATA})
        else:
            from app.services.wa_booking_messages import inr

            words = f"Up to {d['max_discount_percent']}%"
            if d.get("max_discount_amount"):
                words += f" (at most {inr(d['max_discount_amount'])})"
            if d.get("min_booking_amount"):
                words += f"; no discount below {inr(d['min_booking_amount'])}"
            values.append({"label": "Your discount policy", "text": words, "restricted": True})
    elif slot == "packages":
        pk = inp.get("packages") or []
        values.extend(
            {
                "label": p["name"],
                "text": f"{p['min_nights']}+ nights" + (f", up to {p['max_nights']}" if p.get("max_nights") else ""),
            }
            for p in pk
        )
        if not pk:
            step["notes"].append("No published packages: skip this step, or publish trips in your business data.")
    elif slot == "offer_text":
        if text.get("offer_text"):
            values.append({"label": "Offer name", "text": text["offer_text"], "ai": True})
        else:
            step["notes"].append("Write a short name for the offer yourself (no figures).")
    values[:] = [v for v in values if v]
