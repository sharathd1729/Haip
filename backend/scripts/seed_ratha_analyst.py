"""Switch on the AI business analyst + learning loop settings for one workspace (Rathaa), as the owner approved (23 Oct 2026).

  * analyst: daily pulse 09:00, weekly brief Monday 08:30, monthly review 1st 08:30 (IST); delivery by email / WhatsApp OFF
    until the WhatsApp template is approved by Meta and the owner turns it on
  * learning: the owner's default autonomy (replies / prices / routes act within limits; holds + payment links, policy rules
    and ads budget suggest), Build Your Own driving limit 8 h/day, peak dates 24 Dec - 1 Jan, experiments ALLOWED but none started
  * A DRY RUN unless --apply. Writes go through the audited settings services (actor ``seed_ratha_analyst``).

    python3 scripts/seed_ratha_analyst.py --tenant rathaa
    python3 scripts/seed_ratha_analyst.py --tenant rathaa --apply
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.schemas.analyst import AnalystSettings, Delivery, Schedule  # noqa: E402
from app.schemas.learning import LearningSettings  # noqa: E402

ANALYST = AnalystSettings(enabled=True, daily=Schedule(on=True, time="09:00"), weekly=Schedule(on=True, time="08:30"),
                          monthly=Schedule(on=True, time="08:30"), delivery=Delivery(email=False, whatsapp=False))
LEARNING = LearningSettings(paused=False, experiments_allowed=True, byo_max_drive_hours_per_day=8.0)


def apply(db, tenant) -> dict:
    from app.services.analyst import settings as analyst_settings
    from app.services.learning import settings as learning_settings
    return {"analyst": sorted(analyst_settings.update(db, tenant, None, ANALYST, actor="seed_ratha_analyst")),
            "learning": sorted(learning_settings.update(db, tenant, None, LEARNING, actor="seed_ratha_analyst"))}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant", required=True, help="workspace slug, e.g. rathaa")
    ap.add_argument("--apply", action="store_true", help="write the settings (default: dry run)")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant).first()
        if tenant is None:
            raise SystemExit(f"No tenant with slug {args.tenant!r}")
        set_tenant_context(db, tenant.id)
        changes = apply(db, tenant)
        print(json.dumps({"analyst": ANALYST.model_dump(), "learning": LEARNING.model_dump()}, indent=2))
        print(f"\nWould change: analyst {changes['analyst'] or 'nothing'}; learning {changes['learning'] or 'nothing'}")
        if args.apply:
            db.commit()
            print("APPLIED. The first report is written at the next scheduled time; no experiment starts until a report proposes one.")
        else:
            db.rollback()
            print("DRY RUN: nothing written. Run again with --apply.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
