"""
Dev seed script — creates a demo@haip.app user for local development.

This replaces the removed "demo" / "owner-bypass" token hack.
Run once after `docker compose up`:

    python scripts/seed_dev_user.py

Credentials written to stdout. Login at http://localhost:3000.
"""
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.database import SessionLocal
from app.core.security import get_password_hash

DEMO_EMAIL = "demo@haip.app"
DEMO_PASSWORD = "DemoHaip2024!"
DEMO_TENANT_SLUG = "demo"


def run():
    db = SessionLocal()
    try:
        from app.models.tenant import Tenant
        from app.models.user import User, UserRole

        # ── Tenant ──────────────────────────────────────────────────────────────
        tenant = db.query(Tenant).filter_by(slug=DEMO_TENANT_SLUG).first()
        if not tenant:
            tenant = Tenant(
                id=str(uuid.uuid4()),
                name="HAIP Demo",
                slug=DEMO_TENANT_SLUG,
                plan="growth",
                brand_name="HAIP Demo",
            )
            db.add(tenant)
            db.flush()
            print(f"✓ Tenant created: {tenant.id}")
        else:
            print(f"✓ Tenant already exists: {tenant.id}")

        # ── User ─────────────────────────────────────────────────────────────────
        user = db.query(User).filter_by(email=DEMO_EMAIL).first()
        if not user:
            user = User(
                id=str(uuid.uuid4()),
                tenant_id=tenant.id,
                email=DEMO_EMAIL,
                name="Demo Owner",
                hashed_password=get_password_hash(DEMO_PASSWORD),
                role=UserRole.OWNER,
                is_active=True,
                is_verified=True,
            )
            db.add(user)
            db.commit()
            print(f"✓ Demo user created: {DEMO_EMAIL}")
        else:
            print(f"✓ Demo user already exists: {DEMO_EMAIL}")

        print()
        print("=" * 50)
        print(f"  Email:    {DEMO_EMAIL}")
        print(f"  Password: {DEMO_PASSWORD}")
        print(f"  URL:      http://localhost:3000")
        print("=" * 50)

    finally:
        db.close()


if __name__ == "__main__":
    run()
