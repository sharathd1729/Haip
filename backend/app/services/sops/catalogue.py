"""SOP templates, code-defined and versioned (bump `version` on any change to a template's steps or wording).

verify: auto = HAIP checks it (services/sops/checks.py; a check that cannot run asks for a screenshot instead)
        evidence = a screenshot or https link is needed before it can be ticked
        manual = a tick
slots: values filled for this workspace (services/sops/generate.py). rules: platform-rule keys shown with the step.
applies_to: business_kind() values; None = every kind. Phase S1 = Google Business Profile, Instagram, WhatsApp profile;
S2 (catalogue_ota.py) = Facebook Page, OTA listings + promotions per property, TripAdvisor; S3 (catalogue_upkeep.py) =
weekly / monthly upkeep.
The Google steps are the 12 items of the website phase 3 checklist (frontend .../marketing/website/google), folded in here.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    how: str
    verify: str = "manual"
    check: str | None = None
    slots: tuple[str, ...] = ()
    rules: tuple[str, ...] = ()
    due_days: int = 7
    link: tuple[str, str] | None = None  # (label, HAIP page) for a step done inside HAIP
    points: int = 0  # Instagram profile score (marketing_profile_score): points this step is worth out of 100


@dataclass(frozen=True)
class Template:
    key: str
    version: int
    platform: str
    title: str
    summary: str
    recurrence: str  # one_off | weekly | monthly | seasonal
    steps: tuple[Step, ...]
    applies_to: tuple[str, ...] | None = None
    per_property: str = "no"  # no | optional | required


GBP_SETUP = Template(
    key="gbp_setup",
    version=1,
    platform="google_business",
    recurrence="one_off",
    per_property="optional",
    title="Google Business Profile: set up and verify",
    summary="Most guests find a stay on Google Maps before they visit a website. These steps help you show up.",
    steps=(
        Step(
            "claim",
            "Claim your profile",
            "Go to business.google.com, search your business name and claim it (or create it if it is not there).",
            due_days=3,
        ),
        Step(
            "verify",
            "Verify your profile",
            "Google decides how you verify (check in the platform: it may offer video, phone, email or a postcard). "
            "Add a screenshot once your profile says it is verified.",
            verify="evidence",
            due_days=14,
        ),
        Step(
            "category",
            "Pick the main category, then 2-3 extra ones",
            "In Google's category box, type the first words of the suggestion below and pick the closest match. "
            "A suggestion marked Not confirmed has not been checked in Google yet: send a screenshot of what you saw.",
            verify="evidence",
            slots=("categories",),
        ),
        Step(
            "nap",
            "Same name, address and phone everywhere",
            "Use exactly these details on Google. Google trusts matching details on your website and profiles.",
            slots=("nap",),
        ),
        Step(
            "website",
            "Add your website link",
            "Paste this as the profile's website, and as the booking link if Google offers one.",
            slots=("website",),
        ),
        Step(
            "hours",
            "Opening hours and check-in times",
            "Set the hours your team answers, and check-in / check-out times if Google shows them.",
        ),
        Step(
            "photos",
            "Add your photos in this order",
            "Real photos, no text on them. Upload them in this order, then add new ones every month.",
            slots=("photos",),
            rules=("gbp.photo_order", "gbp.photo_min"),
        ),
        Step(
            "amenities",
            "Fill in every amenity",
            "Guests filter on these. Tick each one you have.",
            slots=("amenities",),
        ),
        Step(
            "description",
            "Paste your description",
            "What you are, where, who it suits and what is nearby. No prices, no links.",
            slots=("description",),
            rules=("gbp.description_max",),
        ),
        Step(
            "qa",
            "Add your own questions and answers",
            "Ask and answer the questions guests ask most, so the right answer shows first.",
            slots=("qa",),
        ),
        Step(
            "messages",
            "Show your WhatsApp number",
            "Turn on messaging or add this number, and answer fast: Google shows your response time.",
            slots=("whatsapp_number",),
        ),
        Step(
            "reviews",
            "Ask happy guests for a Google review",
            "Copy your review link from your profile (Ask for reviews) and send it on WhatsApp after check-out. "
            "Reply to every review within two days.",
        ),
        Step(
            "connect",
            "Connect Google to HAIP",
            "In HAIP: Marketing › Studio › Settings, Google. Then HAIP can post for you and bring reviews in.",
            verify="auto",
            check="connected:google_business",
            due_days=14,
            link=("Open Studio settings", "/dashboard/marketing/studio?tab=profile"),
        ),
    ),
)

# v2 (Instagram toolkit phase 3): the steps ARE the 12-item profile score (marketing_profile_score, rubric adapted from
# instagram-agent-skill ig-profile, MIT): each scored step carries its points; measured ones are checked by HAIP.
INSTAGRAM_PROFILE = Template(
    key="instagram_profile",
    version=2,
    platform="instagram",
    recurrence="one_off",
    title="Instagram profile: set up for bookings",
    summary="Your profile is the first thing a guest checks before they message you. Each step adds to your profile "
    "score out of 100 (Studio › Insights).",
    steps=(
        Step(
            "professional",
            "Switch to a professional account",
            "Instagram › Settings › Account type and tools. Business or Creator: check in the platform which fits you.",
            due_days=3,
        ),
        Step(
            "connect",
            "Connect Instagram to HAIP",
            "In HAIP: Settings › Integrations › Instagram. Then DMs reach your Inbox and HAIP can read your profile.",
            verify="auto",
            check="connected:instagram",
            due_days=5,
            link=("Open Integrations", "/dashboard/settings/integrations"),
        ),
        Step(
            "name",
            "Name with what you are and where",
            "The bold Name line (30 characters, not the handle) carries your brand plus what you are and where, in words "
            "guests search. Instagram search reads this field.",
            verify="auto",
            check="instagram_name",
            slots=("ig_name",),
            points=12,
        ),
        Step(
            "bio",
            "Bio line one: who it is for",
            "Line one says who the stay is for and what they get, as a sentence. Not a list of adjectives or emoji "
            "between bars.",
            verify="auto",
            check="instagram_bio",
            slots=("short_bio",),
            rules=("ig.bio_max",),
            points=12,
        ),
        Step(
            "bio_proof",
            "Bio: one proof or how to book",
            "Use the rest of the bio for one piece of proof (a rating, a detail only you have) or one plain way to book.",
            verify="auto",
            check="instagram_bio_body",
            points=8,
        ),
        Step(
            "link",
            "Add one link",
            "Edit profile › Links. One link to where the bio promises; two or more is a menu, and a menu books worse.",
            verify="auto",
            check="instagram_link",
            slots=("links_url",),
            points=8,
        ),
        Step(
            "handle",
            "A handle people can say",
            "Readable, sayable and the same as on your other channels. No stacked underscores or numbers for letters.",
            verify="auto",
            check="instagram_handle",
            points=6,
        ),
        Step(
            "contact", "Add a WhatsApp or contact button", "Edit profile › Contact options.", slots=("whatsapp_number",)
        ),
        Step(
            "category",
            "Pick a category",
            "Edit profile › Category, one that fits the stay. HAIP has no confirmed list for Instagram yet: check in the "
            "platform, then add a screenshot. Counts for the score together with the contact button.",
            verify="evidence",
            points=6,
        ),
        Step(
            "highlights",
            "Add story highlights",
            "Four to six highlights named for what guests ask (Stays, Reviews, How to book, Location), covers consistent.",
            slots=("highlights",),
            points=8,
        ),
        Step(
            "pinned",
            "Pin your 3 best posts",
            "Three pinned posts, three jobs: the place at its best, a guest review, how to book.",
            points=10,
        ),
        Step(
            "grid",
            "First nine posts read at a glance",
            "The first nine covers show what the place is at thumbnail size. Pick reel covers on purpose.",
            points=8,
        ),
        Step(
            "photo",
            "Profile photo that reads small",
            "A logo or one clear image that still reads in a 40-pixel circle.",
            points=6,
        ),
        Step(
            "recent",
            "Post every week",
            "Post at least once a week and reply to the comments on your latest post. HAIP checks your recent posts.",
            verify="auto",
            check="instagram_recent",
            points=10,
        ),
        Step(
            "stories",
            "A story most days",
            "Share a story on most days: the morning view, breakfast, a room being made up.",
            points=6,
        ),
    ),
)

WHATSAPP_PROFILE = Template(
    key="whatsapp_profile",
    version=1,
    platform="whatsapp",
    recurrence="one_off",
    title="WhatsApp Business profile: fill it in",
    summary="Guests see this when they tap your name in WhatsApp.",
    steps=(
        Step(
            "display_name",
            "Display name matches your brand",
            "Your WhatsApp display name should be your business name. HAIP reads it from your connected number.",
            verify="auto",
            check="whatsapp_name",
        ),
        Step(
            "about",
            "Paste your About line",
            "WhatsApp Manager › Phone numbers › Profile. Check the length limit there.",
            slots=("wa_about",),
        ),
        Step("description", "Paste your description", "Same place, Description.", slots=("description",)),
        Step(
            "details", "Address, email and website", "Same place. Use exactly these details.", slots=("nap", "website")
        ),
        Step("photo", "Profile photo", "Use your logo.", slots=("logo",), rules=("wa.profile_photo",)),
        Step(
            "category",
            "Pick a category",
            "Same place, Category: check in the platform, then add a screenshot.",
            verify="evidence",
        ),
    ),
)

from app.services.sops.catalogue_links import LINKS_TEMPLATES  # noqa: E402 -- website SEO agency (links, citations)
from app.services.sops.catalogue_ota import OTA_TEMPLATES  # noqa: E402 -- needs Step/Template above (phase S2)
from app.services.sops.catalogue_upkeep import UPKEEP_TEMPLATES  # noqa: E402 -- phase S3

TEMPLATES: tuple[Template, ...] = (
    GBP_SETUP,
    INSTAGRAM_PROFILE,
    WHATSAPP_PROFILE,
    *OTA_TEMPLATES,
    *UPKEEP_TEMPLATES,
    *LINKS_TEMPLATES,
)
BY_KEY = {t.key: t for t in TEMPLATES}
VERIFY = ("auto", "evidence", "manual")


def applies(t: Template, kind: str | None) -> bool:
    return t.applies_to is None or kind in t.applies_to
