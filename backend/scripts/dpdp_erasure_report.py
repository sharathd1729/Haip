"""DPDP erasure: see what is pending and what the nightly job would erase -- and, with --apply, erase the due requests now.

A DRY RUN unless you pass --apply. For each workspace (or one, with --tenant-slug) it lists the open deletion requests
(guests.deletion_state = "pending"), which are past the 30-day grace period, and how many rows per table the erase would
remove for those. The preview erases inside a savepoint and rolls it back, so nothing is written and no file is touched.
With --apply the due requests are erased exactly as the nightly job does when DPDP_ERASURE_ENABLED is on (audited
dpdp.erasure_completed, stored recordings / media deleted after the commit).

Usage (inside the API container, against production):
    docker compose -f docker-compose.prod.yml exec api python3 scripts/dpdp_erasure_report.py
    docker compose -f docker-compose.prod.yml exec api python3 scripts/dpdp_erasure_report.py --tenant-slug rathaa --apply
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services import dpdp_erasure_service as erasure  # noqa: E402


def preview(db, tenant_id: str) -> dict:
    """Pending / due requests and the rows the erase would remove, without writing anything."""
    requests = erasure.pending_requests(db, tenant_id)
    due = [r for r in requests if r["due"]]
    rows: dict[str, int] = {}
    files = 0
    for r in due:
        nested = db.begin_nested()
        try:
            result = erasure.erase_guest(db, tenant_id, r["guest_id"])
            files += len(result["files"])
            for k, v in result["rows"].items():
                rows[k] = rows.get(k, 0) + v
        finally:
            nested.rollback()
    return {"requests": requests, "due": len(due), "rows": rows, "files": files}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--tenant-slug", help="one workspace (default: all)")
    parser.add_argument("--apply", action="store_true", help="erase the due requests now (default: report only)")
    args = parser.parse_args()
    db = SessionLocal()
    try:
        q = db.query(Tenant)
        if args.tenant_slug:
            q = q.filter_by(slug=args.tenant_slug)
        tenants = q.all()
        if not tenants:
            raise SystemExit(f"No tenant with slug {args.tenant_slug!r}" if args.tenant_slug else "No tenants")
        print("APPLY: erasing due requests" if args.apply else "DRY RUN (nothing written; add --apply to erase the due ones)")
        for t in tenants:
            set_tenant_context(db, t.id)
            p = preview(db, t.id)
            if not p["requests"]:
                continue
            print(f"\n{t.slug}: {len(p['requests'])} deletion request(s), {p['due']} past the 30-day grace period")
            for r in sorted(p["requests"], key=lambda r: r["requested_at"] or ""):
                print(f"  guest {r['guest_id'][:8]}…  requested {r['requested_at'] or '?'}  "
                      f"{'DUE' if r['due'] else 'erases on ' + (r['due_on'] or '?')}")
            if p["due"]:
                print("  would erase:", ", ".join(f"{k} {v}" for k, v in sorted(p["rows"].items()) if v) or "nothing")
                print(f"  stored files: {p['files']}")
            if args.apply and p["due"]:
                out = erasure.run_tenant(db, t.id, apply=True)
                print(f"  ERASED {out['erased']}, failed {len(out['failed'])}, files deleted {out['files']}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    main()
