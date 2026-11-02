"""Starting designs per business type (website phase 4). "Make my website" (website_autobuild) picks one from the
tenant's business type (website_seo.business_kind): the look (palette, fonts, corners), the hero layout, the order and
variants of the sections and the tone of their headings. Everything shown still binds to HAIP data (stays, published
packages and itineraries, approved photos, consented reviews, approved FAQs from the knowledge base); a section with no
data is left out. Copy is short and generic on purpose: nothing here claims a fact about the business.

Section ids are the autobuild ids: stays, book, packages, itinerary, gallery, reviews, faq (hero, cta, contact are fixed).
"""
from typing import Optional

_DEFAULT_ORDER = ["stays", "book", "packages", "itinerary", "gallery", "reviews", "faq"]

STARTERS: dict[str, dict] = {
    "boutique_hotel": {
        "tokens": {"palette": "lamp-night", "display": "playfair", "body": "inter", "radius": "sharp"},
        "hero": "split", "cta": "Check availability",
        "order": ["stays", "book", "gallery", "reviews", "faq", "packages", "itinerary"],
        "variants": {"stays": "rows", "gallery": "grid", "reviews": "grid", "faq": "two-column"},
        "copy": {"stays": ("Rooms", "Rooms and suites"), "book": ("Reservations", "Check availability"),
                 "gallery": ("Inside", "A look around"), "reviews": ("Guests", "From our guest book"),
                 "faq": ("Before you arrive", "Good to know")},
    },
    "resort": {
        "tokens": {"palette": "coast-sand", "display": "cormorant", "body": "manrope", "radius": "soft"},
        "hero": "fullbleed-image", "cta": "Plan your stay",
        "order": ["stays", "gallery", "packages", "book", "reviews", "faq", "itinerary"],
        "variants": {"stays": "feature", "gallery": "filmstrip", "packages": "feature", "reviews": "quote-carousel"},
        "copy": {"stays": ("Stay", "Where you'll stay"), "gallery": ("The resort", "Days here"),
                 "packages": ("Experiences", "Stays and experiences"), "book": ("Book", "Plan your stay"),
                 "reviews": ("Guests", "What guests remember")},
    },
    "service_apartments": {
        "tokens": {"palette": "monsoon-slate", "display": "bricolage", "body": "inter", "radius": "sharp"},
        "hero": "split", "cta": "Check dates",
        "order": ["stays", "book", "faq", "reviews", "gallery", "packages", "itinerary"],
        "variants": {"stays": "rows", "faq": "compact", "reviews": "rating-strip", "gallery": "grid"},
        "copy": {"stays": ("Apartments", "Apartments for short and long stays"), "book": ("Book", "Check dates"),
                 "faq": ("Practical", "Wi-Fi, parking, longer stays"), "reviews": ("Guests", "What guests say")},
    },
    "homestay": {
        "tokens": {"palette": "estate-olive", "display": "fraunces", "body": "karla", "radius": "soft"},
        "hero": "fullbleed-image", "cta": "Ask about dates",
        "order": ["stays", "gallery", "reviews", "book", "faq", "packages", "itinerary"],
        "variants": {"stays": "cards", "gallery": "masonry", "reviews": "quote-carousel", "faq": "accordion"},
        "copy": {"stays": ("Your room", "Stay with us"), "gallery": ("Home", "A look around"),
                 "reviews": ("Guests", "Kind words from guests"), "book": ("Dates", "When would you like to come?"),
                 "faq": ("Good to know", "Before you come")},
    },
    "villa": {
        "tokens": {"palette": "forest-amber", "display": "dm-serif", "body": "figtree", "radius": "soft"},
        "hero": "fullbleed-image", "cta": "Check dates",
        "order": ["stays", "gallery", "book", "reviews", "faq", "packages", "itinerary"],
        "variants": {"stays": "feature", "gallery": "masonry", "reviews": "quote-carousel"},
        "copy": {"stays": ("The villas", "Private villas"), "gallery": ("Photos", "Take a look"),
                 "book": ("Book", "Check dates"), "reviews": ("Guests", "What guests say")},
    },
    "farmhouse": {
        "tokens": {"palette": "estate-olive", "display": "instrument-serif", "body": "source-sans", "radius": "soft"},
        "hero": "fullbleed-image", "cta": "Ask about dates",
        "order": ["stays", "gallery", "book", "faq", "reviews", "packages", "itinerary"],
        "variants": {"stays": "feature", "gallery": "filmstrip", "faq": "two-column"},
        "copy": {"stays": ("The farm", "Stay on the farm"), "gallery": ("Outdoors", "Fields, food and quiet"),
                 "book": ("Dates", "Check dates for your group"), "faq": ("Good to know", "Groups, food and pets")},
    },
    "caravan": {
        "tokens": {"palette": "forest-amber", "display": "bricolage", "body": "figtree", "radius": "soft"},
        "hero": "fullbleed-image", "cta": "Plan my trip",
        "order": ["packages", "itinerary", "stays", "book", "gallery", "reviews", "faq"],
        "variants": {"packages": "cards-3", "itinerary": "timeline", "stays": "cards", "gallery": "masonry"},
        "copy": {"packages": ("Trips", "Pick your trip"), "itinerary": ("Day by day", "How a trip unfolds"),
                 "stays": ("On wheels", "Our caravans"), "book": ("Dates", "Check dates")},
    },
    "travel_agency": {
        "tokens": {"palette": "rani-indigo", "display": "fraunces", "body": "dm-sans", "radius": "pill"},
        "hero": "centered-minimal", "cta": "Plan my trip",
        "order": ["packages", "itinerary", "reviews", "gallery", "faq", "stays", "book"],
        "variants": {"packages": "comparison", "itinerary": "day-cards", "reviews": "grid", "faq": "two-column"},
        "copy": {"packages": ("Journeys", "Trips we plan"), "itinerary": ("A sample route", "Day by day"),
                 "reviews": ("Travellers", "From people who went"), "faq": ("Before you book", "Questions travellers ask")},
    },
}


def starter_for(kind: Optional[str]) -> Optional[dict]:
    return STARTERS.get(kind or "")


def apply(sections: list[dict], kind: Optional[str]) -> tuple[list[dict], Optional[dict]]:
    """Reorder, restyle and retitle the optional sections for this kind. Returns (sections, starter or None)."""
    st = starter_for(kind)
    if st is None:
        return sections, None
    by_id = {s["id"]: s for s in sections}
    out = []
    for sid in st["order"] + [s for s in _DEFAULT_ORDER if s not in st["order"]]:
        s = by_id.get(sid)
        if s is None:
            continue
        s = {**s, "slots": dict(s["slots"])}
        if sid in st["variants"]:
            s["variant"] = st["variants"][sid]
        if sid in st["copy"]:
            s["slots"]["eyebrow"], s["slots"]["heading"] = st["copy"][sid]
        out.append(s)
    return out, st
