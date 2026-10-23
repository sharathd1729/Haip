"""Switch on Rathaa's lead rules (sales meetings, 22-23 Oct 2026).

  * brand_config.lead_validity: the automatic valid-lead rule (KPI D-28) -- a real name, a phone number and a guest
    location of Bengaluru / Bangalore; a missing check-in date is a note, never invalid (require_check_in false).
  * brand_config.reports.daily_lead_email: the 11:00 IST daily lead report email to owners + managers, with the 10:30
    reminder to reservations / concierge to update their leads first.

A DRY RUN unless --apply: prints what would change. --apply writes both through the services' own setters (audited
``lead_validity.settings_changed`` / ``reports.daily_lead_email_changed``, actor seed_ratha_lead_settings). Re-running with
the same values changes nothing.

Usage (inside the API container):
    python3 scripts/seed_ratha_lead_settings.py --tenant rathaa
    python3 scripts/seed_ratha_lead_settings.py --tenant rathaa --apply
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services import lead_validity  # noqa: E402

ACTOR = "seed_ratha_lead_settings"
RATHA_VALIDITY = {"enabled": True, "require_name": True, "require_phone": True, "require_check_in": False,
                  "require_location": False, "allowed_locations": ["Bengaluru", "Bangalore"], "location_field": "guest_location"}
RATHA_DAILY_EMAIL = {"enabled": True, "hour": 11, "minute": 0, "reminder": True}


def plan(tenant) -> dict:
    """{section: (current, wanted)} for each setting that would change."""
    from app.services import lead_report_email
    out = {}
    cur = lead_validity.settings_of(tenant)
    if {k: cur[k] for k in RATHA_VALIDITY} != RATHA_VALIDITY:
        out["lead_validity"] = (cur, {**cur, **RATHA_VALIDITY})
    cur_email = lead_report_email.settings_of(tenant)
    if {k: cur_email[k] for k in RATHA_DAILY_EMAIL} != RATHA_DAILY_EMAIL:
        out["reports.daily_lead_email"] = (cur_email, {**cur_email, **RATHA_DAILY_EMAIL})
    return out


def apply(db, tenant) -> None:
    from app.services import lead_report_email
    lead_validity.put_settings(db, tenant, None, RATHA_VALIDITY, actor=ACTOR)
    lead_report_email.put_settings(db, tenant, None, RATHA_DAILY_EMAIL, actor=ACTOR)


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
        changes = plan(tenant)
        for section, (cur, wanted) in changes.items():
            print(f"{section}:\n  now:  {json.dumps(cur)}\n  will: {json.dumps(wanted)}")
        if not changes:
            print("Nothing to change: the settings are already in place.")
            return 0
        if args.apply:
            apply(db, tenant)
            db.commit()
            print("Applied.")
        else:
            print("\nDry run: nothing written. Re-run with --apply to write it.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
