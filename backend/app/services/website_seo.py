"""Search engines (website phase 3): JSON-LD per v2 page and the kind of business a site is.

business_kind() turns the free-text tenants.business_type into one of the starter kinds (phase 4 picks the starter design
from it too). JSON-LD is built from the SAME bound data the page shows, so it never claims what the page doesn't:
  * the business node: VacationRental (villa, homestay, farmhouse), Hotel (boutique hotel), Resort, TravelAgency, or
    LodgingBusiness; name, url, phone, email, address, photo, social profiles
  * aggregateRating: the average over EVERY rated review HAIP holds (bindings' count/average), never only the good ones;
    review: only reviews the guest consented to show (the reviews section's items), first name only
  * offers / priceRange: only in grounded price mode, from the website price engine's "from" figure
  * FAQPage: the page's FAQ section items (approved, active knowledge entries)
Only for a live page with its host; previews get none.
"""

import re

KINDS = ("boutique_hotel", "resort", "service_apartments", "homestay", "villa", "farmhouse", "caravan", "travel_agency")

_WORDS = (  # first match wins: order matters ("villa_resort" is a villa business, "caravan" before "travel")
    ("caravan", ("caravan", "campervan", "motorhome", "rv")),
    ("villa", ("villa",)),
    ("farmhouse", ("farm",)),
    ("travel_agency", ("travel", "agency", "tour")),
    ("service_apartments", ("apartment", "serviced", "service_apart")),
    ("resort", ("resort",)),
    ("boutique_hotel", ("hotel", "boutique", "inn")),
    ("homestay", ("homestay", "home_stay", "home stay", "airbnb", "bnb", "cottage", "guest_house", "guesthouse")),
)

SCHEMA_TYPE = {
    "boutique_hotel": "Hotel",
    "resort": "Resort",
    "service_apartments": "LodgingBusiness",
    "homestay": "VacationRental",
    "villa": "VacationRental",
    "farmhouse": "VacationRental",
    "caravan": "LodgingBusiness",
    "travel_agency": "TravelAgency",
}


def business_kind(business_type: str | None) -> str | None:
    bt = (business_type or "").strip().lower()
    if bt in KINDS:
        return bt
    flat = bt.replace("-", "_")
    tokens = set(re.split(r"[^a-z]+", bt))
    for kind, words in _WORDS:
        if any(w in tokens or (len(w) >= 4 and w in flat) for w in words):  # "rv"/"inn" only as whole words
            return kind
    return None


def schema_type(business_type: str | None) -> str:
    return SCHEMA_TYPE.get(business_kind(business_type) or "", "LodgingBusiness")


def _sections(doc: dict, stype: str) -> list[dict]:
    return [s for p in doc.get("pages", []) for s in p.get("sections", []) if s.get("type") == stype]


def jsonld(tenant, doc: dict, bound: dict, assets: dict, *, host: str, grounded: bool) -> dict[str, list[dict]]:
    """{page slug: [JSON-LD objects]} for a live v2 site."""
    site = doc.get("site") or {}
    contact = site.get("contact") or {}
    base = f"https://{host}"
    biz: dict = {
        "@context": "https://schema.org",
        "@type": schema_type(tenant.business_type),
        "@id": f"{base}/#business",
        "name": site.get("name") or tenant.name,
        "url": f"{base}/",
    }
    if site.get("tagline"):
        biz["description"] = site["tagline"]
    if contact.get("phone"):
        biz["telephone"] = contact["phone"]
    if contact.get("email"):
        biz["email"] = contact["email"]
    if contact.get("address"):
        biz["address"] = {"@type": "PostalAddress", "streetAddress": contact["address"], "addressCountry": "IN"}
    if assets:
        biz["image"] = [f"{base}/_haip/media/{a}" for a in list(assets)[:3]]
    same = [u for u in (site.get("social") or {}).values() if isinstance(u, str) and u.startswith("https://")]
    if same:
        biz["sameAs"] = same
    reviews = [bound.get(s["id"]) or {} for s in _sections(doc, "reviews")]
    rated = next((r for r in reviews if r.get("count")), None)
    if rated and rated.get("average"):
        biz["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": rated["average"],
            "reviewCount": rated["count"],
            "bestRating": 5,
            "worstRating": 1,
        }
        biz["review"] = [
            {
                "@type": "Review",
                "author": {"@type": "Person", "name": i["name"] or "Guest"},
                "reviewBody": i["quote"],
                **(
                    {"reviewRating": {"@type": "Rating", "ratingValue": i["rating"], "bestRating": 5}}
                    if i.get("rating")
                    else {}
                ),
            }
            for i in rated.get("items", [])[:5]
        ]
    if grounded:
        offers, seen = [], set()
        for s in _sections(doc, "stays") + _sections(doc, "booking"):
            for i in (bound.get(s["id"]) or {}).get("items") or []:
                if i.get("from") and i["id"] not in seen:
                    seen.add(i["id"])
                    offers.append(
                        {
                            "@type": "Offer",
                            "name": i["name"],
                            "priceCurrency": "INR",
                            "price": i["from"]["amount"],
                            "priceSpecification": {
                                "@type": "UnitPriceSpecification",
                                "price": i["from"]["amount"],
                                "priceCurrency": "INR",
                                "unitText": "night",
                            },
                        }
                    )
        if offers:
            biz["makesOffer"] = offers[:10]
            low = min(float(o["price"]) for o in offers)
            biz["priceRange"] = f"From ₹{low:,.0f} per night"
    out: dict[str, list[dict]] = {}
    for page in doc.get("pages", []):
        items = [biz]
        faqs = [
            i
            for s in page.get("sections", [])
            if s.get("type") == "faq"
            for i in (bound.get(s["id"]) or {}).get("items") or []
        ]
        if faqs:
            items.append(
                {
                    "@context": "https://schema.org",
                    "@type": "FAQPage",
                    "mainEntity": [
                        {"@type": "Question", "name": f["q"], "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                        for f in faqs[:20]
                    ],
                }
            )
        out[page["slug"]] = items
    return out
