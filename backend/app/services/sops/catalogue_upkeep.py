"""Phase S3 SOP templates: recurring upkeep (weekly / monthly), every business kind. A new cycle opens on its own
(services/sops/upkeep.py); its due steps become Tasks and overdue steps remind the assignee, then the managers.
"""

from app.services.sops.catalogue import Step, Template

STUDIO_CONTENT = ("Open Studio content", "/dashboard/marketing/studio?tab=content")
STUDIO_REVIEWS = ("Open reviews", "/dashboard/marketing/studio?tab=reviews")

GBP_UPKEEP = Template(
    key="gbp_upkeep",
    version=1,
    platform="google_business",
    recurrence="weekly",
    title="Google profile: weekly upkeep",
    summary="A post, new photos and replies every week keep your profile showing up.",
    steps=(
        Step(
            "post",
            "Post one update on Google",
            "An offer, an event or a seasonal photo. Marketing Studio can post it for you. HAIP sees only posts made "
            "from HAIP: for one made in Google directly, add a screenshot.",
            verify="auto",
            check="gbp_posted_7d",
            due_days=5,
            link=STUDIO_CONTENT,
        ),
        Step(
            "reviews",
            "Reply to new reviews",
            "Reply to every review within two days, good or bad.",
            verify="auto",
            check="google_reviews_answered",
            due_days=3,
            link=STUDIO_REVIEWS,
        ),
        Step("photos", "Add one or two new photos", "Real, recent photos. No text on them.", due_days=6),
    ),
)

GBP_MONTHLY = Template(
    key="gbp_monthly",
    version=1,
    platform="google_business",
    recurrence="monthly",
    title="Google profile: monthly check",
    summary="Once a month, make sure what Google shows is still right.",
    steps=(
        Step(
            "info",
            "Your details are still right",
            "Compare your profile with these details.",
            slots=("nap", "website"),
            due_days=7,
        ),
        Step(
            "hours",
            "Hours and holidays",
            "Set special hours for holidays coming up (where to set them: check in the platform).",
            due_days=7,
        ),
        Step(
            "photos",
            "Photo order",
            "Move your best photos to the front.",
            slots=("photos",),
            rules=("gbp.photo_order",),
            due_days=10,
        ),
        Step("qa", "Questions and answers", "Add the questions guests asked this month.", slots=("qa",), due_days=10),
    ),
)

MAPS_HYGIENE = Template(
    key="maps_hygiene",
    version=1,
    platform="google_business",
    recurrence="monthly",
    title="Google Maps and Search: monthly listing check",
    summary="Google trusts a business whose details match everywhere.",
    steps=(
        Step(
            "same_everywhere",
            "Same name, address and phone everywhere",
            "Check these match on your website, Google, Instagram, Facebook, WhatsApp and every booking site.",
            slots=("nap",),
            due_days=7,
        ),
        Step(
            "website",
            "Your website is live",
            "Google reads your website's details and structured data.",
            verify="auto",
            check="website_live",
            due_days=7,
            link=("Open website", "/dashboard/marketing/website"),
        ),
        Step(
            "duplicates",
            "No duplicate pins on Maps",
            "Search Google Maps for your business name. If two pins show, ask Google to merge or remove one: check in "
            "the platform how.",
            due_days=10,
        ),
    ),
)

INSTAGRAM_UPKEEP = Template(
    key="instagram_upkeep",
    version=1,
    platform="instagram",
    recurrence="weekly",
    title="Instagram: weekly upkeep",
    summary="Regular posts and quick replies turn followers into enquiries.",
    steps=(
        Step(
            "post",
            "Post at least once this week",
            "HAIP reads your latest posts from your connected account.",
            verify="auto",
            check="instagram_posted_7d",
            due_days=5,
            link=STUDIO_CONTENT,
        ),
        Step(
            "replies",
            "Reply to comments and messages",
            "Answer within a day.",
            due_days=2,
            link=("Open Inbox", "/dashboard/inbox"),
        ),
        Step("highlights", "Refresh a story highlight", "Add this week's best story to a highlight.", due_days=6),
    ),
)

REVIEWS_REPLY = Template(
    key="reviews_reply",
    version=1,
    platform="google_business",
    recurrence="weekly",
    title="Reviews: reply and ask, every week",
    summary="Replies show future guests you care; asking brings the next review.",
    steps=(
        Step(
            "google",
            "Google reviews answered",
            "HAIP drafts a reply for each one; a person posts it.",
            verify="auto",
            check="google_reviews_answered",
            due_days=3,
            link=STUDIO_REVIEWS,
        ),
        Step(
            "booking_sites",
            "Reviews on booking sites",
            "Open each booking site you are on and reply to new reviews within two days.",
            due_days=4,
        ),
        Step("ask", "Ask this week's guests", "Send your review link to guests who checked out this week.", due_days=6),
    ),
)

UPKEEP_TEMPLATES: tuple[Template, ...] = (GBP_UPKEEP, GBP_MONTHLY, MAPS_HYGIENE, INSTAGRAM_UPKEEP, REVIEWS_REPLY)
