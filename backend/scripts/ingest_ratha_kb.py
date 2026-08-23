"""
One-off ingestion: seed the AI concierge's knowledge base for Ratha from
RathaOS_AI_Knowledge_Transfer_v1.0.docx, so the bot can actually answer
questions about the vehicle, add-ons, routes and common objections instead
of only handling availability/price grounding + generic small talk.

This is a hand-curated set of guest-facing entries, NOT a mechanical dump
of the whole document. RathaOS is a staff/governance document, not a guest
FAQ file -- it explicitly distinguishes Approved / Working / Historical /
Open-Unverified knowledge and has a whole section titled "Historical
variants -- retrieval only, never auto-quote" listing several conflicting
past prices. knowledge_entries has no such status field (it's a flat
approved/active FAQ store), so rather than build that out for one ingest,
every section touching a concrete price, commission %, or legal/commercial
figure is deliberately EXCLUDED here -- not because retrieval is unsafe
(price_policy.detect_price already hard-blocks any price-shaped text in a
draft, digit-based, before it can reach a guest, regardless of source) but
because none of those numbers are the tenant's live, authoritative rate --
that's calculator_service/RatePlan's job, not this narrative doc's. Feeding
stale figures into the KB would only add noise a guest's question could
surface, with no upside.

Also excluded as not guest-facing at all: lead scoring internals, the CRM
data model/taxonomy, AI behaviour policy (already enforced in code via
price_policy/escalation_policy/the grounding guard, not something to
surface as a quotable KB snippet), partner/legal/commercial specifics,
analytics, open risks, and the implementation/governance sections.

Idempotent: re-running skips any (source_ref, question) pair already in
the DB, so a second run after adding more curated entries only inserts
the new ones.

Run (on the VPS, inside the api/worker container -- needs Postgres+pgvector
and a live NVIDIA embeddings key, neither available against local SQLite):
  docker compose -f docker-compose.prod.yml exec api \
    python scripts/ingest_ratha_kb.py --dry-run
  docker compose -f docker-compose.prod.yml exec api \
    python scripts/ingest_ratha_kb.py
"""
import sys
import os
import argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.tenant import Tenant
from app.models.knowledge import KnowledgeEntry
from app.services import knowledge_service

SOURCE_REF = "RathaOS_AI_Knowledge_Transfer_v1.0.docx"
_SLUGS = ("ratha", "rathaa")

# (category, question, content) -- category matches the existing UI taxonomy
# in frontend/src/app/dashboard/settings/knowledge/page.tsx.
ENTRIES: list[tuple[str, str, str]] = [
    ("other", "What is Ratha?",
     "Ratha — Retreat on the Move — is a private, premium mobile retreat by "
     "Jade Hospitainment (Jade Retreats). It's not a taxi, bus or ordinary "
     "caravan rental — it's a self-contained private space that travels "
     "with you to scenic and experiential locations that fixed-room hotels "
     "can't reach. Guests are paying for privacy, flexibility, access, "
     "curation and a shared experience, not just vehicle kilometres."),

    ("amenities", "What does the Ratha vehicle look like / what's inside?",
     "Ratha is built on an Ashok Leyland platform, about 30 feet long. "
     "Inside: four reclining chairs for travel/dining/meetings, one "
     "hydraulic queen bed plus a large sofa-cum-bed (comfort depends on "
     "group composition), a separate private bathroom and toilet with "
     "hot-water shower, a kitchenette near the driver with a serving "
     "window, fridge, water dispenser and crockery/cutlery, "
     "air-conditioning, large-screen entertainment with audio and mood "
     "lighting, a panoramic arched roof (roughly 6.5–7 ft at peak) with "
     "blackout curtains, and a wardrobe plus internal/underbody luggage "
     "storage. Every amenity is subject to the live vehicle readiness "
     "check before a trip."),

    ("amenities", "How many guests can Ratha carry / can everyone sleep comfortably?",
     "Ratha's working experience capacity is 6–8 guests. Travel capacity, "
     "legal capacity and sleeping comfort are different things — don't "
     "assume all 6–8 can sleep with equal comfort. Always confirm the "
     "adult/children mix and whether any guests would need a property room "
     "instead of sleeping in the caravan."),

    ("other", "How fast does Ratha travel / how do I estimate arrival time?",
     "Ratha's working top speed is about 70 km/h — arrival-time estimates "
     "should reflect this, not car-speed assumptions."),

    ("addons", "What add-on experiences can we book?",
     "Bicycles and camping kit, karaoke and projector/movie setup, bonfire "
     "and BBQ, telescope and stargazing, a spa/wellness toolkit, a curator "
     "or local guide, and culinary/wellness/entertainment/adventure "
     "modules — plus partner-property stays, meals and activities. "
     "Bonfire, BBQ, projector, awning, tents and other outdoor setups "
     "depend on weather, permissions, safety and the specific site's "
     "rules, so confirm before promising one for a particular location."),

    ("other", "What experience formats/packages does Ratha offer?",
     "Full Day (around 8 hours) for family days, corporate off-sites and "
     "day leisure; Sunset + Dinner (around 8 hours) for couples, "
     "celebrations and sunset dining; Sunrise (around 8 hours) for "
     "couples, wellness and photography; Night Camping (around 20 hours) "
     "for friends, family and celebration camping; 1 Night/2 Day and 2 "
     "Night/3 Day formats combining the vehicle with a curated route and "
     "optional partner-property stay; and multi-day Karnataka circuits "
     "(1–10 days) plus interstate journeys such as Rameshwaram–Dhanushkodi "
     "or Goa–Dandeli–Gokarna. Exact timings and durations should be "
     "confirmed per booking, not assumed fixed."),

    ("other", "What does a typical Ratha day look like?",
     "A typical day: depart Bengaluru after a readiness check and guest "
     "briefing, travel to the chosen destination with planned halts, "
     "lunch/relaxation or a site activity, a scenic stop or high tea, "
     "evening BBQ/music/bonfire/movie where the site allows it, overnight "
     "in the caravan, a tent, or a partner property room depending on the "
     "confirmed package, then a sunrise activity, breakfast and return "
     "with time/distance reconciliation and feedback."),

    ("routes", "Where around North Bangalore can Ratha take us?",
     "North Bengaluru corridor: Nandi Hills, Bhoganandishwara, Devanahalli "
     "Fort, Hesaraghatta, Ghati Subramanya, Makalidurga, Gundamagere, "
     "Avathi, Grover Zampa, Jakkur Flying Club, Adiyogi/Sannidhi, "
     "Varalakonda and Gudibande. Commercial-vehicle entry, operating "
     "hours, parking and any partner-site arrangements should be "
     "confirmed before booking a specific stop."),

    ("routes", "Where around South Bangalore can Ratha take us?",
     "South Bengaluru corridor: Kabbaladurga, TK Falls, Bilikal, the "
     "Bannerghatta belt, Pyramid Valley, Art of Living, Big Banyan and "
     "Mekedatu/Sangama. Forest, monument and private-site permissions can "
     "change, so confirm current access before booking."),

    ("routes", "Does Ratha go to Wonderland Treehouse / Sarjapur?",
     "Yes — the East corridor includes Wonderland Treehouse near Sarjapur, "
     "with forest, pool, horse-riding and deck experiences. Confirm "
     "current property availability and inclusions before booking."),

    ("routes", "Does Ratha do longer Karnataka trips like Kabini, Coorg or Hampi?",
     "Yes — Karnataka long routes include Kabini, Bandipur, K Gudi, Coorg, "
     "Hampi and other similar circuits. Any implied partnership or "
     "endorsement (for example with JLR or KSTDC) should never be claimed "
     "to a guest unless it's been formally, written-approved — say only "
     "what's currently confirmed."),

    ("routes", "Can Ratha go interstate, like to Goa or Rameshwaram?",
     "Interstate journeys such as Rameshwaram–Dhanushkodi or "
     "Goa–Dandeli–Gokarna are things Ratha can be inspired by and discuss, "
     "but any unstandardized/custom route needs a real operations "
     "feasibility check (road access, permits, driver hours, parking, "
     "utilities) before it can be confirmed or paid for — never promise an "
     "interstate trip is locked in during the chat itself."),

    ("policy", "Can Ratha go anywhere we want / a custom destination?",
     "Ratha can go to a lot of places, but any destination outside the "
     "standard, already-validated routes needs a feasibility check first "
     "— road width, turning radius, height clearance, gradient, parking "
     "and legal access all matter for a 30-foot vehicle. Be enthusiastic "
     "about the idea, but don't confirm a custom route until operations "
     "has checked it."),

    ("faq", "Isn't a tempo traveller or hotel cheaper / why not use one of those instead?",
     "A tempo traveller or a hotel room solves a different need — Ratha "
     "combines a private, room-like environment with travel and curated "
     "stops in one experience, so guests aren't packing/unpacking, "
     "checking in, or splitting up across a group. It's a fair comparison "
     "to make, and worth asking the guest what matters more to them: pure "
     "cost, or the privacy and flexibility of a moving private space."),

    ("faq", "Is the bathroom/washroom clean and private?",
     "Ratha has a separate, private bathroom and toilet with a hot-water "
     "shower (subject to the live readiness check before each trip). "
     "Avoid making specific hygiene/sanitation guarantees beyond what's "
     "actually been verified — if the guest wants proof, offer to share "
     "the vehicle's verified readiness checklist or evidence if "
     "available."),

    ("faq", "Is Ratha safe? Who's driving?",
     "Ratha is driven by a licensed HMV (Heavy Motor Vehicle) driver, and "
     "every route is checked before a trip as part of the readiness "
     "process. For any real safety, breakdown, accident or medical "
     "concern during a trip, this needs to go straight to a human on the "
     "operations/emergency chain — don't try to resolve a live safety "
     "issue over chat."),

    ("faq", "Is the AC/power reliable the whole trip?",
     "AC and power depend on the vehicle's live readiness check before "
     "each trip — don't guarantee they'll work perfectly without that "
     "confirmation. If a guest specifically asks, say it's checked before "
     "every dispatch rather than promising it outright."),

    ("faq", "What if it rains / what happens to outdoor plans?",
     "Outdoor elements — bonfire, BBQ, stargazing, awning setups — can "
     "change with weather. Confirm the core (indoor) plan is unaffected "
     "and mention that outdoor extras have a weather-dependent "
     "contingency, rather than promising a specific outdoor activity will "
     "definitely happen."),

    ("other", "What kind of trips is Ratha good for?",
     "Couples looking for a private, romantic sunrise/sunset escape; "
     "families wanting to travel together without repeatedly packing or "
     "checking in/out; friend groups planning a celebration, camping or "
     "music-and-food outing; corporates wanting an off-site, team day or "
     "reward trip with a mobile hospitality setup; and content creators "
     "who want a distinctive, production-friendly mobile space across "
     "changing backdrops."),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report what would be written without writing")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.slug.in_(_SLUGS)).first()
        if not tenant:
            print(f"No tenant found with slug in {_SLUGS} — aborting.")
            return

        print(f"Tenant: {tenant.name} ({tenant.id}, slug={tenant.slug})")
        print(f"Ingesting {len(ENTRIES)} curated entries from {SOURCE_REF}\n")

        created = 0
        skipped = 0
        failed = 0
        for category, question, content in ENTRIES:
            existing = (
                db.query(KnowledgeEntry)
                .filter_by(tenant_id=tenant.id, source_ref=SOURCE_REF, question=question)
                .first()
            )
            if existing:
                print(f"  [skip] already exists: {question!r}")
                skipped += 1
                continue

            print(f"  {'[dry-run] would add' if args.dry_run else '[add]'} ({category}) {question!r}")
            if args.dry_run:
                created += 1
                continue

            entry = KnowledgeEntry(
                tenant_id=tenant.id,
                category=category,
                question=question,
                content=content,
                source="manual",
                source_ref=SOURCE_REF,
                review_status="approved",
                is_active=True,
            )
            db.add(entry)
            db.commit()

            ok = knowledge_service.embed_entry(db, entry)
            if ok:
                created += 1
            else:
                failed += 1
                print(f"    embedding failed for {entry.id} — see kb_embed_failed log; row kept, retry via the Knowledge Base settings page.")

        print(f"\nDone. Created: {created}, skipped (already present): {skipped}, embedding failures: {failed}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
