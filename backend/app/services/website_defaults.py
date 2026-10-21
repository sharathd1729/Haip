"""The first draft of a site, built only from what HAIP already knows (no AI): the business profile from Marketing
Studio, the properties, the business type and the region. The AI developer (website_ai_service) rewrites the copy
later; this draft is complete and truthful on its own, so a site never starts empty or invented."""
from typing import Optional

from app.services import website_blocks as wb

# Region keywords -> theme pack. The first match in the profile's city/description wins.
_PACK_HINTS = [
    ("goa", ("goa", "konkan", "gokarna", "alibaug", "sindhudurg")),
    ("kerala", ("kerala", "alleppey", "alappuzha", "kochi", "cochin", "munnar", "wayanad", "kumarakom", "varkala", "kovalam")),
    ("rajasthan", ("rajasthan", "jaipur", "udaipur", "jodhpur", "jaisalmer", "pushkar", "bikaner", "ranthambore")),
    ("himalaya", ("himachal", "manali", "shimla", "mussoorie", "rishikesh", "dehradun", "uttarakhand", "ladakh", "leh",
                  "kasol", "dharamshala", "nainital", "sikkim", "darjeeling", "kashmir", "spiti")),
    ("chettinad", ("chettinad", "karaikudi", "tamil", "pondicherry", "puducherry", "madurai", "kanchipuram")),
    ("malnad", ("coorg", "kodagu", "chikmagalur", "chikkamagaluru", "sakleshpur", "malnad", "kodachadri", "agumbe",
                "ooty", "wayanad", "karnataka", "bangalore", "bengaluru", "kabini")),
]


def pick_pack(*texts: Optional[str]) -> str:
    hay = " ".join(t for t in texts if t).lower()
    for pack, words in _PACK_HINTS:
        if any(w in hay for w in words):
            return pack
    return "malnad"


def pick_personality(business_type: Optional[str], tone: Optional[str]) -> str:
    t = (tone or "").lower()
    if any(w in t for w in ("fun", "playful", "quirky", "young", "vibrant")):
        return "playful"
    if any(w in t for w in ("heritage", "royal", "classic", "traditional", "palace")):
        return "heritage"
    return "calm"


def _b(btype: str, layout: str = "", background: str = "page", **props) -> dict:
    return {"type": btype, "props": {"id": wb.new_id(), "layout": layout, "background": background, **props}}


def _unit_words(business_type: Optional[str]) -> tuple[str, str]:
    bt = (business_type or "").lower()
    if "caravan" in bt or "camper" in bt:
        return "caravan", "caravans"
    if "villa" in bt:
        return "villa", "villas"
    if "homestay" in bt:
        return "room", "rooms"
    if "apartment" in bt or "serviced" in bt:
        return "apartment", "apartments"
    return "stay", "stays"


def build(*, name: str, business_type: Optional[str], profile: dict, city: Optional[str], contact: dict,
          booking_mode: str) -> dict:
    """A complete, validated document. Copy is plain and factual; nothing about prices, offers or reviews is made up."""
    one, many = _unit_words(business_type)
    tagline = (profile.get("tagline") or "").strip()
    about = (profile.get("description") or "").strip()
    usps = [u for u in (profile.get("usps") or []) if isinstance(u, str) and u.strip()][:6]
    where = (city or profile.get("city") or "").strip()
    kicker = f"{many.capitalize()} in {where}" if where else many.capitalize()
    caravan = one == "caravan"
    book_cta = "Plan my trip" if caravan or booking_mode in ("request", "enquiry") else "Check dates"
    book_link = "/contact" if booking_mode == "enquiry" else "/book"

    home = [
        _b("Hero", "split", kicker=kicker, title=tagline or f"Welcome to *{name}*",
           text=about[:280], chips=[], cta_label=book_cta, cta_link=book_link),
    ]
    if booking_mode != "enquiry":
        home.append(_b("BookingBar", cta_label="Check availability"))
    home.append(_b("Stays", "cards", kicker=f"Our {many}", heading=f"Choose your {one}", intro="", limit="all"))
    if usps:
        home.append(_b("Highlights", "image_right", kicker="Why guests choose us", heading=f"Why {name}", items=usps))
    home.append(_b("Amenities", kicker="Every stay has", heading="", icons=["wifi", "parking"] if not caravan else ["driver", "kitchen", "bonfire"]))
    home.append(_b("Band", background="brand", kicker="Book direct", heading="Talk to us on WhatsApp",
                   text="Ask anything about dates, plans and what's included. A real person replies.",
                   chips=[], cta_label="Contact us", cta_link="/contact"))

    pages = [
        {"id": "home", "key": "home", "title": "Home", "path": "/", "nav": False,
         "seo": {"title": f"{name}{' | ' + kicker if where else ''}"[:70], "description": (about or tagline)[:160]},
         "content": home},
        {"id": "stays", "key": "stays", "title": many.capitalize(), "path": "/stays", "nav": True,
         "seo": {"title": f"Our {many} | {name}"[:70], "description": f"See every {one} at {name}, with photos, what's included and free dates."[:160]},
         "content": [_b("Text", "left", kicker=kicker, heading=f"Our {many}", body=""),
                     _b("Stays", "list", heading="", kicker="", intro="", limit="all")]},
        {"id": "stay", "key": "stay", "title": f"{one.capitalize()} page", "path": "/stays/[slug]", "nav": False,
         "seo": {"title": f"{{stay}} | {name}"[:70], "description": ""},
         "content": [_b("StayDetail", intro=""), _b("Amenities", kicker="What's included", heading="", icons=[])]},
        {"id": "about", "key": "", "title": "About", "path": "/about", "nav": True,
         "seo": {"title": f"About {name}"[:70], "description": (about or f"The story of {name}.")[:160]},
         "content": [_b("Text", "left", kicker="Our story", heading=f"About {name}", body=about[:1500])]},
        {"id": "contact", "key": "contact", "title": "Contact", "path": "/contact", "nav": True,
         "seo": {"title": f"Contact {name}"[:70], "description": f"WhatsApp, call or email {name}. We reply quickly."[:160]},
         "content": [_b("Contact", heading="Talk to a real person", text="WhatsApp is the fastest way to reach us.", show_form=True)]},
        {"id": "policies", "key": "policies", "title": "Policies", "path": "/policies", "nav": False,
         "seo": {"title": f"Cancellation, payments and house rules | {name}"[:70], "description": f"How booking, payment and cancellation work at {name}."[:160]},
         "content": [_b("Policies", heading="Policies", extra="")]},
        {"id": "manage", "key": "manage", "title": "My booking", "path": "/my-booking", "nav": False,
         "seo": {"title": f"My booking | {name}"[:70], "description": ""},
         "content": [_b("ManageBooking", heading="Find your booking")]},
    ]
    if booking_mode != "enquiry":
        pages.append({"id": "book", "key": "book", "title": "Book", "path": "/book", "nav": False,
                      "seo": {"title": f"Book your stay | {name}"[:70], "description": f"Pick dates and book {name} directly."[:160]},
                      "content": [_b("BookingEngine", heading="Book your stay", intro="")]})
    doc = {
        "schema": wb.SCHEMA,
        "theme": {"pack": pick_pack(where, profile.get("description"), name),
                  "personality": pick_personality(business_type, profile.get("tone"))},
        "site": {"name": name, "tagline": tagline, "logo": "", "contact": contact, "social": {}},
        "pages": pages,
    }
    clean, _ = wb.validate_doc(doc)
    return clean
