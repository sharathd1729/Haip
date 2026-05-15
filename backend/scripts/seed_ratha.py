"""
Seed script — creates Ratha tenant, owner user, property, rubric, and sample data.
Run: python scripts/seed_ratha.py
"""
import sys, os, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.database import SessionLocal
from app.core.security import get_password_hash

def run():
    db = SessionLocal()
    try:
        from app.models.tenant import Tenant
        from app.models.user import User
        from app.models.property import Property, RatePlan
        from app.models.score import Rubric
        from app.models.guest import Guest
        from app.models.inquiry import Inquiry

        # ── Tenant ──────────────────────────────────────────────────────────
        existing = db.query(Tenant).filter_by(slug="ratha").first()
        if existing:
            print("Ratha tenant already exists — skipping.")
            tenant = existing
        else:
            tenant = Tenant(
                id=str(uuid.uuid4()),
                name="Ratha Travels",
                slug="ratha",
                plan="growth",
                ivr_provider="callerdesk",
                brand_name="Ratha — Luxury Caravan Journeys",
                brand_config={"primary_color": "#0B1F3A", "accent": "#14B8A6"},
            )
            db.add(tenant)
            db.flush()
            print(f"✓ Tenant created: {tenant.id}")

        # ── Owner user ───────────────────────────────────────────────────────
        if not db.query(User).filter_by(email="sharath@ratha.in").first():
            owner = User(
                id=str(uuid.uuid4()),
                tenant_id=tenant.id,
                name="Sharath D.",
                email="sharath@ratha.in",
                hashed_password=get_password_hash("ratha2026"),
                role="owner",
            )
            db.add(owner)
            print(f"✓ Owner: sharath@ratha.in / ratha2026")

        # ── Concierge ────────────────────────────────────────────────────────
        if not db.query(User).filter_by(email="ravi@ratha.in").first():
            concierge = User(
                id=str(uuid.uuid4()),
                tenant_id=tenant.id,
                name="Ravi Kumar",
                email="ravi@ratha.in",
                hashed_password=get_password_hash("ratha2026"),
                role="concierge",
            )
            db.add(concierge)
            print(f"✓ Concierge: ravi@ratha.in / ratha2026")

        # ── Property ─────────────────────────────────────────────────────────
        if not db.query(Property).filter_by(tenant_id=tenant.id).first():
            prop = Property(
                id=str(uuid.uuid4()),
                tenant_id=tenant.id,
                name="Ratha Caravan Fleet",
                slug="ratha-fleet",
                type="caravan",
                city="Bangalore",
                state="Karnataka",
                description="Luxury caravans for experiential journeys across South India — Coorg, Wayanad, Hampi, Rajasthan.",
                max_adults=4,
                bedrooms=1,
                amenities=["private-chef", "bonfire", "stargazing", "couples-spa", "butler"],
                brand_voice="Warm, knowledgeable, slightly poetic. We don't sell trips — we craft memories. Speak to the experience, not the price.",
                faqs=[
                    {"q": "What is the cancellation policy?", "a": "Full refund 14 days before departure; 50% within 14 days; no refund within 72 hours."},
                    {"q": "Do you accommodate dietary restrictions?", "a": "Yes — vegetarian, vegan, Jain, and most allergies. Please inform us at booking."},
                    {"q": "Is the caravan AC?", "a": "Yes — all caravans have climate control, luxury bedding, and en-suite bathrooms."},
                ],
            )
            db.add(prop)
            db.flush()

            rate = RatePlan(
                id=str(uuid.uuid4()),
                tenant_id=tenant.id,
                property_id=prop.id,
                name="Signature Caravan — 2 Pax",
                base_price_per_night=12000,
                currency="INR",
                min_nights=2,
                inclusions=["breakfast", "dinner", "bonfire", "butler"],
            )
            db.add(rate)
            print(f"✓ Property + Rate Plan created")

        # ── Default QA Rubric ─────────────────────────────────────────────────
        if not db.query(Rubric).filter_by(tenant_id=tenant.id, is_default=True).first():
            rubric = Rubric(
                id=str(uuid.uuid4()),
                tenant_id=tenant.id,
                name="Ratha QA Rubric v1",
                version="1.0",
                is_default=True,
                criteria=[
                    {"id": "greeting",    "name": "Warm greeting + brand intro",          "weight": 8,  "method": "yes_no"},
                    {"id": "discovery",   "name": "Discovery — occasion, group, budget",   "weight": 12, "method": "zero_three"},
                    {"id": "expertise",   "name": "Itinerary & route expertise",           "weight": 12, "method": "zero_three"},
                    {"id": "pricing",     "name": "Pricing transparency",                  "weight": 10, "method": "yes_no"},
                    {"id": "empathy",     "name": "Empathy on luxury cues",                "weight": 10, "method": "zero_three"},
                    {"id": "objection",   "name": "Objection handling",                    "weight": 10, "method": "zero_three"},
                    {"id": "next_step",   "name": "Clear next step committed",             "weight": 12, "method": "yes_no"},
                    {"id": "close",       "name": "Close + commitment attempt",            "weight": 12, "method": "yes_no"},
                    {"id": "pii",         "name": "No PII leakage",                        "weight": 8,  "method": "auto_fail"},
                    {"id": "tone",        "name": "Professional tone throughout",          "weight": 6,  "method": "zero_three"},
                ],
            )
            db.add(rubric)
            print(f"✓ QA Rubric created")

        # ── Sample guests + inquiries ─────────────────────────────────────────
        sample_guests = [
            {"phone": "+919876543210", "name": "Priya Sharma",  "email": "priya@gmail.com",   "city": "Bangalore"},
            {"phone": "+917654321098", "name": "Kiran Reddy",   "email": "kiran.r@gmail.com", "city": "Hyderabad"},
            {"phone": "+919765432109", "name": "Rahul Mehta",   "email": None,                 "city": "Mumbai"},
        ]
        for g_data in sample_guests:
            if not db.query(Guest).filter_by(tenant_id=tenant.id, phone=g_data["phone"]).first():
                guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, **g_data)
                db.add(guest)
        db.flush()
        print(f"✓ Sample guests seeded")

        db.commit()
        print("\n✅ Seed complete! Login with:")
        print("   sharath@ratha.in / ratha2026  (owner)")
        print("   ravi@ratha.in    / ratha2026  (concierge)")
        print("   OR demo accounts: owner@haip.dev / haip2026")

    except Exception as e:
        db.rollback()
        print(f"❌ Seed failed: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    run()
