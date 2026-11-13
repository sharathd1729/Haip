"""
Switch a workspace to (or from) PERSONAL mode: one person's own phone calls, read like a NeoSapien memory
(services/personal_calls.py). The workspace keeps every call from the Calls app, its calls get the personal read instead
of the hospitality QA score, and the web app shows only Calls and Reminders.

    python scripts/set_personal_workspace.py --tenant-slug srinivas-calls          # dry run (default): shows the change
    python scripts/set_personal_workspace.py --tenant-slug srinivas-calls --apply  # writes it (audited)
    ... --off --apply                                                               # back to a business workspace

Create the workspace first with the normal sign-up (it provisions the default modules), then run this.
Calls already analysed keep their old read; only calls analysed after the switch get the personal one.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.models  # noqa: E402,F401  (registers every table)
from app.core.audit import append_audit  # noqa: E402
from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services.personal_calls import MODE_KEY, PERSONAL  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant-slug", required=True)
    ap.add_argument("--off", action="store_true", help="switch back to a business workspace")
    ap.add_argument("--apply", action="store_true", help="write the change (default: dry run)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if tenant is None:
            print(f"No workspace with slug {args.tenant_slug!r}.")
            return 1
        set_tenant_context(db, tenant.id)
        config = dict(tenant.brand_config or {})
        before = config.get(MODE_KEY) or "business"
        after = "business" if args.off else PERSONAL
        print(f"{tenant.name} ({tenant.slug}): {before} -> {after}")
        if before == after:
            print("Nothing to change.")
            return 0
        if not args.apply:
            print("Dry run. Add --apply to write it.")
            return 0
        if args.off:
            config.pop(MODE_KEY, None)
        else:
            config[MODE_KEY] = PERSONAL
        tenant.brand_config = config
        append_audit(db=db, tenant_id=tenant.id, actor_user_id="system", action="workspace.mode_changed",
                     target_type="tenant", target_id=tenant.id, payload={"from": before, "to": after})
        db.commit()
        print("Done.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
