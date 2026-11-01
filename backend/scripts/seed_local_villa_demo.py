"""Seed a made-up villa business ("Palmgrove Villas", slug demo-villas) into the LOCAL database, to check the Ops villa
screens (Ops today, the stay file). Never real Jade or guest data: every name, number and amount here is invented.

Same guards as seed_local_demo.py: refuses unless DATABASE_URL is localhost and ENVIRONMENT=development; re-running wipes
only this demo tenant and recreates it. No Celery task, LLM or WhatsApp call is made.

    cd backend && python scripts/seed_local_villa_demo.py     # DEMO_PASSWORD=... to choose the password

Stays it leaves, one per state the screens show: arriving tomorrow (checks half done, meals planned), staying (deposit held,
today's lunch not confirmed by the cook, a clean due), checked out (inspection found a broken lamp), and a free villa.
"""

import os
import secrets
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from seed_local_demo import assert_local_target, uid, wipe  # noqa: E402

SLUG = "demo-villas"
BRAND = "Palmgrove Villas (demo)"


def run() -> None:
    from app.core.config import settings

    assert_local_target(settings.DATABASE_URL, settings.ENVIRONMENT)

    import app.models  # noqa: F401  registers every model
    from app.core.database import SessionLocal
    from app.core.security import get_password_hash
    from app.models.guest import Guest
    from app.models.module import Module, WorkspaceModule
    from app.models.ops import StaffDuty, StaffProfile
    from app.models.property import Property, Stay
    from app.models.stay_finance import StayDeposit, StayPayment
    from app.models.tenant import Tenant
    from app.models.user import User, UserRole
    from app.schemas.ops_files import CheckInIn, ExpenseIn, MealIn
    from app.services import ops_money as money
    from app.services import ops_stay_meals as meals
    from app.services import ops_stay_service as stays
    from app.services import ops_trip_service as trips
    from app.services.authz_service import seed_default_capabilities
    from app.services.pipeline_stage_service import seed_default_pipeline_stages
    from app.services.workspace_context import provision_default_modules

    db = SessionLocal()
    old = db.query(Tenant).filter_by(slug=SLUG).first()
    if old:
        print(f"Wiping existing villa demo tenant {old.id} ...")
        wipe(db, old.id)

    tid = uid()
    db.add(
        Tenant(
            id=tid,
            name=BRAND,
            slug=SLUG,
            plan="growth",
            business_type="villa_resort",
            brand_name=BRAND,
            timezone="Asia/Kolkata",
            brand_config={"price_disclosure": "handoff"},
        )
    )
    db.flush()
    provision_default_modules(db, tid)
    seed_default_pipeline_stages(db, tid)
    seed_default_capabilities(db, tid)
    have = {m for (m,) in db.query(WorkspaceModule.module_id).filter_by(workspace_id=tid)}
    for m in db.query(Module).all():
        if m.id not in have:
            db.add(WorkspaceModule(id=uid(), workspace_id=tid, module_id=m.id, enabled=True))

    password = os.environ.get("DEMO_PASSWORD") or secrets.token_urlsafe(9)
    hashed = get_password_hash(password)
    owner = User(
        id=uid(),
        tenant_id=tid,
        email="owner@palmgrove.example",
        name="Priya Owner",
        hashed_password=hashed,
        role=UserRole.OWNER,
        is_active=True,
        consent_recorded_at=datetime.now(UTC),
    )
    manager = User(
        id=uid(),
        tenant_id=tid,
        email="manager@palmgrove.example",
        name="Mohan Manager",
        hashed_password=hashed,
        role=UserRole.MANAGER,
        is_active=True,
        consent_recorded_at=datetime.now(UTC),
    )
    db.add_all([owner, manager])

    villas = []
    for n, name in enumerate(("Villa Amara", "Villa Banyan", "Villa Coral"), start=1):
        p = Property(
            id=uid(),
            tenant_id=tid,
            name=name,
            slug=f"demo-villa-{n}",
            type="villa",
            city="Bengaluru",
            description="Made-up pool villa for local testing.",
        )
        db.add(p)
        villas.append(p)
    db.flush()

    # One caretaker per villa, one cook and one cleaner for all (the file suggests a person only when exactly one fits).
    def person(name, phone, duty, property_id=None):
        s = StaffProfile(
            id=uid(),
            tenant_id=tid,
            name=name,
            phone_e164=phone,
            active=True,
            whatsapp_opt_in_at=datetime.now(UTC),
        )
        db.add(s)
        db.flush()
        db.add(StaffDuty(tenant_id=tid, staff_id=s.id, duty=duty, property_id=property_id))
        return s

    for i, v in enumerate(villas):
        person(f"Caretaker {v.name.split()[-1]}", f"+919000010{i:03d}", "caretaker", v.id)
    person("Cook Lata", "+919000020001", "fnb")
    person("Cleaner Ravi", "+919000020002", "housekeeping")
    db.flush()

    today = date.today()

    def stay(villa, guest, start, nights, total, adults=4, children=0, status="confirmed"):
        g = Guest(id=uid(), tenant_id=tid, name=guest, phone=f"+91900003{start + 50:04d}")
        db.add(g)
        s = Stay(
            id=uid(),
            tenant_id=tid,
            guest_id=g.id,
            property_id=villa.id,
            check_in=today + timedelta(days=start),
            check_out=today + timedelta(days=start + nights),
            check_in_time="14:00",
            check_out_time="11:00",
            adults=adults,
            children=children,
            status=status,
            total_amount=Decimal(total),
        )
        db.add(s)
        db.flush()
        return s

    def pay(s, amount):
        db.add(
            StayPayment(
                tenant_id=tid, stay_id=s.id, amount=Decimal(amount), method="upi", paid_on=today - timedelta(days=3)
            )
        )
        db.flush()

    def deposit(s, amount="10000"):
        db.add(StayDeposit(tenant_id=tid, stay_id=s.id, amount=Decimal(amount), status="pending"))
        db.flush()

    def ready(f):
        for i in trips.readiness_items(db, f):
            if i.critical and i.source != "system":
                stays.set_item(db, f, i.key, "green", "Demo: photo checked", user_id=owner.id)

    # Arriving tomorrow: half the checks done, two meals planned, nothing confirmed yet.
    a = stay(villas[0], "Demo Guest Arjun", 1, 3, "54000", adults=6, children=2)
    pay(a, "27000")
    fa = trips.ensure_file(db, tid, a)
    for key in ("pool", "bedrooms", "kitchen"):
        stays.set_item(db, fa, key, "green", "Demo: photo checked", user_id=owner.id)
    meals.add_meal(db, fa, MealIn(date=a.check_in.isoformat(), meal="dinner", guests=8, food="mixed"), owner.id)
    meals.add_meal(
        db, fa, MealIn(date=(a.check_in + timedelta(days=1)).isoformat(), meal="breakfast", guests=8), owner.id
    )

    # Staying (5 nights, arrived 2 days ago): deposit held, lunch today not confirmed, a clean due tomorrow.
    b = stay(villas[1], "Demo Guest Meera", -2, 5, "90000", adults=4)
    pay(b, "90000")
    deposit(b)
    fb = trips.ensure_file(db, tid, b)
    ready(fb)
    stays.check_in(db, fb, CheckInIn(keys_handed=True, deposit_collected=True, note="Demo check-in"), owner.id)
    meals.add_meal(
        db, fb, MealIn(date=today.isoformat(), meal="lunch", guests=4, food="veg", notes="No onion"), owner.id
    )
    money.add_expense(
        db, fb, ExpenseIn(category="groceries", amount=Decimal("2350"), vendor="Demo Mart"), actor_id=owner.id
    )

    # Checked out this morning: inspection found a broken lamp, deposit still held, a little balance left.
    c = stay(villas[2], "Demo Guest Kabir", -3, 3, "48000", adults=5)
    pay(c, "45000")
    deposit(c, "8000")
    fc = trips.ensure_file(db, tid, c)
    ready(fc)
    stays.check_in(db, fc, CheckInIn(keys_handed=True, deposit_collected=True), owner.id)
    stays.check_out(db, fc, owner.id)
    for i in trips.readiness_items(db, fc, "inspection"):
        bad = i.key == "damage"
        stays.set_item(
            db, fc, i.key, "red" if bad else "green", "Demo: bedside lamp broken" if bad else None, user_id=owner.id
        )

    db.commit()
    print(f"Villa demo tenant: {BRAND} (slug {SLUG}, id {tid})")
    print("Sign in as owner@palmgrove.example or manager@palmgrove.example")
    print(f"Password (shown once): {password}")
    print("Open /dashboard/ops for Ops today; each stay file is linked from there.")


if __name__ == "__main__":
    run()
