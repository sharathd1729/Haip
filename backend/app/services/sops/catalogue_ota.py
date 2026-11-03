"""Phase S2 SOP templates: OTA listings and promotions (one per property), TripAdvisor, Facebook Page.

There is no OTA API in HAIP and HAIP never logs in to an OTA: a person pastes the values. Listing copy comes from the
Studio's OTA copy drafts (marketing_ota_copies); programme names (e.g. MMT Black) come only from the platform rules
catalogue, all "Not confirmed" until the HAIP team checks them. Promotions are `seasonal`; phase S3 opens the next cycle.
"""

from app.services.sops.catalogue import Step, Template

# platform key -> (name shown, business kinds it applies to: docs/sops/DYNAMIC_SOPS_PLAN.md §3)
OTAS = {
    "airbnb": ("Airbnb", ("villa", "farmhouse", "homestay", "service_apartments", "boutique_hotel")),
    "booking": ("Booking.com", ("boutique_hotel", "resort", "service_apartments", "homestay", "villa")),
    "makemytrip": ("MakeMyTrip / Goibibo", ("boutique_hotel", "resort", "villa", "homestay", "service_apartments")),
    "agoda": ("Agoda", ("boutique_hotel", "resort", "service_apartments", "homestay", "villa")),
}
LIMIT_KEYS = {
    "airbnb": ("title", "summary", "the_space", "guest_access", "neighbourhood", "getting_around"),
    "booking": ("headline", "description", "highlights"),
    "makemytrip": ("title", "about", "highlights", "house_rules"),
    "agoda": ("description", "highlights"),
}
CALENDAR_SYNC = ("Open calendar links", "/dashboard/settings/calendar-sync")


def _listing(platform: str) -> Template:
    name, kinds = OTAS[platform]
    return Template(
        key=f"{platform}_listing",
        version=1,
        platform=platform,
        recurrence="one_off",
        per_property="required",
        applies_to=kinds,
        title=f"{name} listing: set up and polish",
        summary=f"Guests compare listings side by side on {name}. These steps make this property's listing complete.",
        steps=(
            Step(
                "open",
                "Open this property's listing",
                f"Log in to {name} yourself and open this property's listing.",
                due_days=3,
            ),
            Step(
                "copy",
                "Paste the listing text",
                "Paste each field below into the same field on the listing. HAIP cut each one to the limit in its "
                "catalogue; the platform's own limit may differ, so check in the platform.",
                slots=("ota_copy",),
                rules=tuple(f"ota.{platform}.{k}_max" for k in LIMIT_KEYS[platform]),
            ),
            Step(
                "photos",
                "Upload photos in this order",
                "Real photos, no text on them, best first.",
                slots=("photos",),
                rules=("gbp.photo_order",),
            ),
            Step("amenities", "Tick every amenity you have", "Guests filter on these.", slots=("amenities",)),
            Step(
                "rules",
                "House rules and check-in times",
                "Use the same times and rules everywhere.",
                slots=("house_rules",),
            ),
            Step(
                "calendar",
                "Connect the calendars both ways",
                f"Paste HAIP's calendar link into {name} so HAIP bookings block those dates there, and add {name}'s "
                "calendar link in HAIP so its bookings block dates here. HAIP checks the second part.",
                verify="auto",
                check="ical_import",
                slots=("ical",),
                link=CALENDAR_SYNC,
            ),
            Step(
                "prices",
                "Prices and discounts",
                "Set prices in the platform yourself. Use the promotions checklist for seasonal offers.",
            ),
            Step(
                "live",
                "Add the link to the live listing",
                "Open the listing as a guest would and paste its link here.",
                verify="evidence",
                due_days=14,
            ),
        ),
    )


def _promos(platform: str) -> Template:
    name, kinds = OTAS[platform]
    return Template(
        key=f"{platform}_promos",
        version=1,
        platform=platform,
        recurrence="seasonal",
        per_property="required",
        applies_to=kinds,
        title=f"{name} promotions for the coming season",
        summary=f"Set up {name} offers before the busy dates, inside your own discount rules.",
        steps=(
            Step(
                "season",
                "Look at the dates coming up",
                "Long weekends and holidays in the next 90 days.",
                slots=("season",),
                due_days=3,
            ),
            Step(
                "free",
                "See which dates are still free",
                "Offers work best on dates that are still open.",
                slots=("free_dates",),
                due_days=3,
            ),
            Step(
                "programmes",
                "Choose the programmes to join",
                f"{name} programmes HAIP knows of are below. What each one needs and costs: check in the platform.",
                slots=("programmes",),
            ),
            Step(
                "discount",
                "Stay inside your discount rules",
                "Any offer you set must follow your own discount policy.",
                slots=("discount_policy",),
            ),
            Step(
                "packages",
                "Package deals",
                "Where the platform offers packages, list these trips or stays.",
                slots=("packages",),
            ),
            Step(
                "offer",
                "Name the offer",
                "A short name for the offer. Put the numbers in the platform's own fields.",
                slots=("offer_text",),
            ),
            Step(
                "set_up",
                "Set it up and add a screenshot",
                "Create the offer in the platform, then add a screenshot of it here.",
                verify="evidence",
                due_days=10,
            ),
        ),
    )


TRIPADVISOR = Template(
    key="tripadvisor_listing",
    version=1,
    platform="tripadvisor",
    recurrence="one_off",
    per_property="optional",
    title="TripAdvisor: claim and complete your listing",
    summary="Many travellers check TripAdvisor reviews before they book.",
    steps=(
        Step(
            "claim",
            "Find and claim your listing",
            "Search your business on TripAdvisor and claim it. Which listing type fits you: check in the platform.",
            due_days=5,
        ),
        Step("description", "Paste your description", "Same text as your Google profile.", slots=("description",)),
        Step("photos", "Add your photos in this order", "Best first.", slots=("photos",), rules=("gbp.photo_order",)),
        Step("website", "Add your website link", "Paste it as the listing's website.", slots=("website",)),
        Step(
            "reviews",
            "Ask happy guests for a review",
            "Copy your review link from TripAdvisor and send it after the stay.",
        ),
        Step("live", "Add the link to your listing", "Paste the listing's link here.", verify="evidence", due_days=14),
    ),
)

FACEBOOK_PAGE = Template(
    key="facebook_page",
    version=1,
    platform="facebook_page",
    recurrence="one_off",
    title="Facebook Page: set up for enquiries",
    summary="Your Page shows up in Facebook search and carries your WhatsApp button.",
    steps=(
        Step(
            "connect",
            "Connect your Page to HAIP",
            "In HAIP: Marketing › Studio › Settings, Facebook. Then HAIP can post for you.",
            verify="auto",
            check="connected:facebook_page",
            due_days=7,
            link=("Open Studio settings", "/dashboard/marketing/studio?tab=profile"),
        ),
        Step(
            "category",
            "Pick a category",
            "Page settings › Category. HAIP has no confirmed list for Facebook yet: check in the platform, then add a "
            "screenshot.",
            verify="evidence",
        ),
        Step("about", "Paste your description", "Page › About › Intro and details.", slots=("description",)),
        Step("website", "Add your website link", "Page › About › Contact info.", slots=("website",)),
        Step(
            "whatsapp",
            "Add a WhatsApp button",
            "Page › Add a button › Send WhatsApp message.",
            slots=("whatsapp_number",),
        ),
        Step("hours", "Opening hours", "Set the hours your team answers."),
        Step(
            "photos",
            "Profile and cover photo",
            "Your logo as the profile photo, your best photo as the cover.",
            slots=("logo",),
        ),
        Step("instagram", "Link your Instagram", "Page settings › Linked accounts › Instagram."),
    ),
)

OTA_TEMPLATES: tuple[Template, ...] = (
    FACEBOOK_PAGE,
    *(_listing(p) for p in OTAS),
    *(_promos(p) for p in OTAS),
    TRIPADVISOR,
)
