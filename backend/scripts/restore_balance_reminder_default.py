"""One-off: let the new balance-reminder default reach workspaces that never chose.

Until Nov 2026 every save of Settings > Invoice details stored ``brand_config.payments.auto_balance_reminder = false``
even when nobody touched the switch, so "never chosen" and "switched off" look the same in the data. The audit trail
tells them apart: a person turning it off left a ``settings.invoice_profile_updated`` change to false. Workspaces whose
false has no such change get the key removed (= the default: on once Razorpay is connected and ratha_balance_due_v1 is
approved). An owner's real "off" is never touched. Logic: balance_reminder_service.restore_unchosen_off.

A DRY RUN unless you pass --apply: prints one word per workspace (no guest data). Idempotent. One transaction per workspace.

Usage (inside the API container):
    docker compose -f docker-compose.prod.yml exec api python3 scripts/restore_balance_reminder_default.py --all-tenants
    docker compose -f docker-compose.prod.yml exec api python3 scripts/restore_balance_reminder_default.py --tenant-slug rathaa --apply
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services import balance_reminder_service  # noqa: E402


def run(db, tenants, apply: bool) -> dict:
    counts: dict[str, int] = {}
    for tenant in tenants:
        set_tenant_context(db, tenant.id)
        result = balance_reminder_service.restore_unchosen_off(db, tenant, apply=apply)
        if apply:
            db.commit()
        else:
            db.rollback()
        counts[result] = counts.get(result, 0) + 1
        if result != "not_false":
            print(f"  {tenant.slug}: {result}{'' if apply or result != 'restored' else ' (would restore)'}")
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    who = ap.add_mutually_exclusive_group(required=True)
    who.add_argument("--tenant-slug")
    who.add_argument("--all-tenants", action="store_true")
    ap.add_argument("--apply", action="store_true", help="write the change (default: dry run, nothing written)")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        if args.all_tenants:
            tenants = db.query(Tenant).order_by(Tenant.slug).all()
        else:
            tenants = db.query(Tenant).filter_by(slug=args.tenant_slug).all()
            if not tenants:
                print(f"No tenant with slug {args.tenant_slug!r}")
                return 1
        print("APPLIED" if args.apply else "DRY RUN (nothing written; add --apply)")
        counts = run(db, tenants, args.apply)
        print("Totals: " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
