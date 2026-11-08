"""Links and citations (website SEO agency, owner doc fix #11): where other sites mention and link to the business.

A person does every step on the other site; HAIP never posts, logs in, scrapes or pays. No platform rules exist for this
(app/data/sop_rules/links.json is empty on purpose): the steps are plain good practice, never a platform's policy.
The outreach list and the messages to send come from the SEO agency's weekly run (website_seo_roles.links_citations).
"""

from app.services.sops.catalogue import Step, Template

GROW = ("Open Website > Grow", "/dashboard/marketing/website/grow")

LINKS_CITATIONS = Template(
    key="links_citations",
    version=1,
    platform="links",
    recurrence="monthly",
    title="Links and citations: other sites that mention you",
    summary="Google trusts a business that local tourism sites, partners and guests link to. Earn links; never buy them.",
    steps=(
        Step(
            "tourism_sites",
            "Listed on your local tourism sites",
            "Find your state and district tourism portals and local travel guides. Ask to be listed with the same name, "
            "address, phone and website as everywhere else.",
            slots=("nap", "website"),
            due_days=10,
        ),
        Step(
            "partners",
            "Partners link to you",
            "Ask the businesses you work with (activity operators, event planners, restaurants nearby) to link to your "
            "website, and link back to them. Only real partners.",
            slots=("website",),
            due_days=14,
        ),
        Step(
            "creators",
            "Creators who stayed link to you",
            "Send this month's outreach messages from Website > Grow. Ask creators who stayed to add your website to "
            "their post, blog or link in bio.",
            due_days=14,
            link=GROW,
        ),
        Step(
            "same_details",
            "Every mention has the same details",
            "Where a site already mentions you, check the name, address and phone match your Google profile. Ask them to "
            "fix any that differ.",
            slots=("nap",),
            due_days=21,
        ),
        Step(
            "no_paid_links",
            "No paid or swapped links",
            "Never pay for a link, buy a 'link package' or join a link swap. Google can stop showing sites that do.",
            due_days=21,
        ),
    ),
)

LINKS_TEMPLATES: tuple[Template, ...] = (LINKS_CITATIONS,)
