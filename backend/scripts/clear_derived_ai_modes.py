"""One-off: clear the creation-time copies of the workspace AI mode stored on conversations.

`conversations.ai_mode` used to be filled with the workspace's WhatsApp/Instagram setting (mostly "shadow") when a thread was
created. The real mode is resolved per reply from the workspace setting (app/services/ai_mode_service.py), so those copies are
stale and mislead any report or screen that reads the column. Only "off" is a real per-thread override (Inbox "AI on" switch,
guest asked for a person, read-only personal-WhatsApp mirror); it is never touched. Everything else becomes NULL
(= follow the workspace setting), which changes no reply behaviour.

A DRY RUN unless you pass --apply: prints counts per stored value only (no guest data). Idempotent: a second run finds nothing.
One transaction per workspace (row-level security context set per workspace).

Usage (inside the API container):
    docker compose -f docker-compose.prod.yml exec api python3 scripts/clear_derived_ai_modes.py --tenant-slug rathaa
    docker compose -f docker-compose.prod.yml exec api python3 scripts/clear_derived_ai_modes.py --tenant-slug rathaa --apply
    docker compose -f docker-compose.prod.yml exec api python3 scripts/clear_derived_ai_modes.py --all-tenants [--apply]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services import ai_mode_service  # noqa: E402


def run(db, tenants, apply: bool) -> int:
    """Clear derived modes for each tenant (one commit per tenant). Returns the total rows cleared / to clear."""
    total = 0
    for tenant in tenants:
        set_tenant_context(db, tenant.id)
        counts = ai_mode_service.clear_derived_modes(db, tenant.id, apply=apply)
        if apply:
            db.commit()
        else:
            db.rollback()
        n = sum(counts.values())
        total += n
        detail = ", ".join(f"{v!r}: {c}" for v, c in sorted(counts.items())) or "nothing to clear"
        print(f"  {tenant.slug}: {'cleared' if apply else 'would clear'} {n} ({detail})")
    return total


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
        total = run(db, tenants, args.apply)
        print(f"{'Cleared' if args.apply else 'Would clear'} {total} conversation(s). 'off' rows left as they are.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
