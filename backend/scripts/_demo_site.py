"""The demo tenant's website, built with the v2 builder (SiteSpec). Called by seed_local_demo.py after photos are seeded.

Made-up business only (Wanderwheel Caravans): never Ratha/Jade data. Seeds what the sections bind to (two published itineraries,
approved FAQs, three guest reviews with recorded consent), creates the site, then a v2 draft from SPEC through the same service
the API uses (website_spec_service.create_draft) and publishes it as the owner. The three pages use all 8 section types x 3
variants between them, so the local site doubles as a visual check of the renderer.
"""
from datetime import datetime, timezone

WANDERWHEEL_SPEC = {
    "spec_version": 2,
    "site": {"name": "Wanderwheel Caravans", "tagline": "Slow road trips from Bengaluru, driver-host included", "ref_prefix": "WW",
             "contact": {"phone": "+91 90000 00000", "whatsapp": "+91 90000 00000", "email": "hello@wanderwheel.example",
                         "address": "Indiranagar, Bengaluru"}},
    "tokens": {"palette": "forest-amber", "display": "fraunces", "body": "figtree", "radius": "soft", "motion": "calm"},
    "pages": [
        {"slug": "/", "title": "Home", "nav": False,
         "seo": {"title": "Wanderwheel Caravans · slow road trips from Bengaluru",
                 "description": "Caravan road trips to misty hills and quiet coasts, with a driver-host, a real bed and breakfast on the road."},
         "sections": [
             {"id": "hero", "type": "hero", "variant": "fullbleed-image",
              "slots": {"eyebrow": "Caravan road trips from Bengaluru", "headline": "Wake up where the *road* ends",
                        "subhead": "Your own room on wheels, a driver-host who knows the back roads, and mornings with nobody else around.",
                        "cta_label": "Plan my trip on WhatsApp"}},
             {"id": "packages", "type": "packages", "variant": "cards-3",
              "slots": {"eyebrow": "Journeys", "heading": "Pick the pace", "intro": "Every journey includes the caravan, the driver-host and breakfast."}},
             {"id": "route", "type": "itinerary", "variant": "timeline", "slots": {"eyebrow": "Day by day", "key": "misty-hills-2n"}},
             {"id": "photos", "type": "gallery", "variant": "masonry", "slots": {"eyebrow": "On the road", "heading": "What the mornings look like", "limit": 9}},
             {"id": "words", "type": "reviews", "variant": "quote-carousel", "slots": {"eyebrow": "Guests", "heading": "In their words"}},
             {"id": "faq", "type": "faq", "variant": "accordion", "slots": {"heading": "Good to know", "limit": 6}},
             {"id": "cta", "type": "booking-cta", "variant": "banner",
              "slots": {"heading": "Tell us your dates", "text": "We reply on WhatsApp with a route and the price for your group."}},
             {"id": "contact", "type": "contact", "variant": "split", "slots": {"eyebrow": "Visit", "heading": "Where we start"}},
         ]},
        {"slug": "/journeys", "title": "Journeys", "nav": True,
         "seo": {"title": "Journeys · Wanderwheel Caravans",
                 "description": "Compare our caravan journeys: weekend loops in the hills and an overnight drive to the coast."},
         "sections": [
             {"id": "journeys-hero", "type": "hero", "variant": "centered-minimal",
              "slots": {"eyebrow": "Journeys", "headline": "Two routes, *one* slow pace", "subhead": "Hills or coast. Pick one, we plan the rest."}},
             {"id": "compare", "type": "packages", "variant": "comparison", "slots": {"heading": "Compare journeys"}},
             {"id": "coast", "type": "itinerary", "variant": "day-cards", "slots": {"eyebrow": "Sample route", "key": "coastal-1n"}},
             {"id": "strip", "type": "gallery", "variant": "filmstrip", "slots": {"heading": "Along the way", "limit": 8}},
             {"id": "questions", "type": "faq", "variant": "two-column", "slots": {"eyebrow": "Before you book", "heading": "Questions guests ask"}},
             {"id": "enquire", "type": "booking-cta", "variant": "inline-form",
              "slots": {"heading": "Ask for your dates", "text": "Leave your number and we'll send a plan on WhatsApp.", "cta_label": "Or message us now"}},
             {"id": "reach", "type": "contact", "variant": "minimal", "slots": {"heading": "Talk to a person"}},
         ]},
        {"slug": "/about", "title": "About", "nav": True,
         "seo": {"title": "About · Wanderwheel Caravans",
                 "description": "Who we are, what a caravan trip with us is like, and what guests say after their first morning on the road."},
         "sections": [
             {"id": "about-hero", "type": "hero", "variant": "split",
              "slots": {"eyebrow": "About us", "headline": "A room, a road, and *no* check-in desk",
                        "subhead": "We started Wanderwheel to make the drive part of the holiday."}},
             {"id": "praise", "type": "reviews", "variant": "grid", "slots": {"heading": "Guests on their trips"}},
             {"id": "signature", "type": "packages", "variant": "feature", "slots": {"eyebrow": "Most booked", "keys": ["weekend-escape", "sunset-overnight"]}},
             {"id": "grid", "type": "gallery", "variant": "grid", "slots": {"limit": 6}},
             {"id": "rating", "type": "reviews", "variant": "rating-strip"},
             {"id": "hills-days", "type": "itinerary", "variant": "accordion", "slots": {"heading": "The hills, day by day", "key": "misty-hills-2n"}},
             {"id": "quick", "type": "faq", "variant": "compact", "slots": {"heading": "Quick answers", "limit": 4}},
             {"id": "card", "type": "contact", "variant": "card", "slots": {"heading": "Say hello", "show_map": False}},
             {"id": "bar", "type": "booking-cta", "variant": "sticky-bar", "slots": {"heading": "Ready when you are"}},
         ]},
    ],
}

ITINERARIES = [
    ("misty-hills-2n", {"name": "Misty Hills Loop", "destination_key": "misty-hills", "nights": 2, "package_keys": ["weekend-escape"],
                        "days": [{"day": 1, "title": "Out of the city, into the hills", "stops": ["Bengaluru", "Coffee Estate Camp"],
                                  "overnight_location": "Coffee Estate Camp", "notes": "Leave after breakfast; lunch at a planters' cafe."},
                                 {"day": 2, "title": "Waterfall morning, estate walk", "stops": ["Waterfall Point", "Coffee Estate Camp"],
                                  "overnight_location": "Coffee Estate Camp"},
                                 {"day": 3, "title": "Slow drive home", "stops": ["Base"]}]}),
    ("coastal-1n", {"name": "Coastal Sunset Drive", "destination_key": "coastal-drive", "nights": 1, "package_keys": ["sunset-overnight"],
                    "days": [{"day": 1, "title": "To the lighthouse for sunset", "stops": ["Bengaluru", "Lighthouse Beach"],
                              "overnight_location": "Lighthouse Beach"},
                             {"day": 2, "title": "Fishing village breakfast, home", "stops": ["Fishing Village", "Base"]}]}),
]

FAQS = [
    ("Who drives the caravan?", "A trained driver-host drives and parks. You don't need a licence or any driving experience."),
    ("Can we bring our dog?", "Yes. Pets are welcome on every journey; tell us when you enquire so we bring a bed and bowls."),
    ("Is there a washroom on board?", "Yes, every caravan has a private washroom, hot water and fresh linen."),
    ("What happens if it rains?", "Monsoon trips are our favourite. Routes are chosen for the season and we change plans if a road closes."),
    ("How many people fit?", "Up to four adults sleep comfortably. Ask us about families with small children."),
    ("When do I pay?", "Your driver-host confirms the plan on WhatsApp first; payment details follow with the confirmation."),
]

REVIEWS = [
    ("Meera Demo", 5, "We woke up to mist over the coffee estate and nobody else around. The driver-host had chai ready before we were up."),
    ("Kabir Sampleson", 5, "Our dog loved it as much as we did. Easy to plan on WhatsApp and everything was exactly as promised."),
    ("Isha Placeholder", 4, "The coastal drive at sunset was the highlight of our year. Bring a jacket for the night by the sea."),
]


def seed(db, tenant, owner) -> str:
    """Seed the v2 demo site for `tenant`. Returns the site's hostname."""
    from app.models.knowledge import KnowledgeEntry
    from app.models.marketing import MarketingGuestReview
    from app.services import business_data_service as bds
    from app.services import website_service as svc
    from app.services import website_spec_service as wspec
    from app.services import website_version_service as vs

    now = datetime.now(timezone.utc)
    for key, data in ITINERARIES:
        rec = bds.create_draft(db, tenant.id, "itinerary", key, data, owner.id)
        bds.publish(db, tenant.id, rec.id, owner.id)
    for i, (q, a) in enumerate(FAQS):
        db.add(KnowledgeEntry(tenant_id=tenant.id, category="faq", question=q, content=a, source="manual",
                              review_status="approved", is_active=True, priority=len(FAQS) - i))
    for i, (name, rating, text) in enumerate(REVIEWS):
        db.add(MarketingGuestReview(tenant_id=tenant.id, source="google", external_id=f"demo-review-{i}", rating=rating,
                                    reviewer=name, comment=text, reviewed_at=f"2026-0{7 + i}-1{i}T10:00:00Z",
                                    consent_note="Demo: guest agreed (made up)", consent_by=owner.id, consent_at=now))
    db.flush()
    site = svc.create_site(db, tenant, actor_id=owner.id)
    v, problems = wspec.create_draft(db, site, WANDERWHEEL_SPEC, actor_id=owner.id, origin="seed", note="Demo site (v2 builder)")
    vs.publish(db, site, v.id, owner)
    db.commit()
    if problems:
        print("Demo site notes:", "; ".join(problems))
    return svc.primary_host(db, site)
