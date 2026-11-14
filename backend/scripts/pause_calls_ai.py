"""
Pause (or resume) call transcription + AI analysis for ONE workspace (services/calls_ai_pause.py). Calls and recordings
keep arriving and are stored; only the speech-to-text and model calls wait. Other workspaces are not touched.

    python scripts/pause_calls_ai.py --tenant-slug jade-hospitainment            # dry run (default)
    python scripts/pause_calls_ai.py --tenant-slug jade-hospitainment --apply    # pause (audited)
    ... --resume --apply                                                          # resume; calls from the last 2 days
                                                                                  # waiting for transcription are picked up
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.models  # noqa: E402,F401  (registers every table)
from app.core.audit import append_audit  # noqa: E402
from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services.calls_ai_pause import KEY  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant-slug", required=True)
    ap.add_argument("--resume", action="store_true", help="resume transcription + analysis")
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
        before = bool(config.get(KEY))
        after = not args.resume
        print(f"{tenant.name} ({tenant.slug}): call AI {'paused' if before else 'running'} -> {'paused' if after else 'running'}")
        if before == after:
            print("Nothing to change.")
            return 0
        if not args.apply:
            print("Dry run. Add --apply to write it.")
            return 0
        if after:
            config[KEY] = True
        else:
            config.pop(KEY, None)
        tenant.brand_config = config
        append_audit(db=db, tenant_id=tenant.id, actor_user_id="system", action="calls_ai.paused" if after else "calls_ai.resumed",
                     target_type="tenant", target_id=tenant.id, payload={"paused": after})
        db.commit()
        print("Done.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
