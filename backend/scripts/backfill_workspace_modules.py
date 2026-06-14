"""
Backfill workspace_modules for existing tenants.

Maps current tenant config signals → module subscriptions:
  - voice_platform set          → calls module
  - whatsapp_phone_number_id set → whatsapp module
  - instagram integration active → instagram module
  - stays exist                  → channel_manager module
  - (always)                    → leads360, analytics modules

Run once after migration 031 is applied:
  cd backend && python scripts/backfill_workspace_modules.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.tenant import Tenant
from app.models.module import Module, WorkspaceModule
from app.models.integration import Integration
from app.models.property import Stay
from app.models.base import gen_uuid
from datetime import datetime, timezone

NOW = datetime.now(timezone.utc)


def detect_modules_for_tenant(db, tenant) -> list[str]:
    codes = []
    if tenant.voice_platform or tenant.ivr_provider:
        codes.append("calls")
    if tenant.whatsapp_phone_number_id:
        codes.append("whatsapp")
    ig = db.query(Integration).filter(
        Integration.tenant_id == tenant.id,
        Integration.kind == "instagram",
        Integration.status == "active",
    ).first()
    if ig:
        codes.append("instagram")
    if db.query(Stay.id).filter(Stay.tenant_id == tenant.id).first():
        codes.append("channel_manager")
    # All existing tenants get leads360 + analytics (they were using these features)
    codes.extend(["leads360", "analytics", "ask_haip"])
    return list(set(codes))


def main():
    db = SessionLocal()
    try:
        module_map = {m.code: m.id for m in db.query(Module).all()}
        if not module_map:
            print("ERROR: modules table is empty — run migration 031 first")
            return

        tenants = db.query(Tenant).filter(Tenant.is_active == True).all()
        print(f"Backfilling {len(tenants)} tenants...")

        for tenant in tenants:
            codes = detect_modules_for_tenant(db, tenant)
            for code in codes:
                module_id = module_map.get(code)
                if not module_id:
                    print(f"  WARN: module '{code}' not found in registry, skipping")
                    continue
                existing = db.query(WorkspaceModule).filter(
                    WorkspaceModule.workspace_id == tenant.id,
                    WorkspaceModule.module_id == module_id,
                ).first()
                if not existing:
                    db.add(WorkspaceModule(
                        id=gen_uuid(),
                        workspace_id=tenant.id,
                        module_id=module_id,
                        enabled=True,
                        activated_at=NOW,
                    ))
            print(f"  {tenant.slug}: {codes}")

        db.commit()
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
