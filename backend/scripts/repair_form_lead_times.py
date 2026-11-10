"""
One-off: lead-form leads imported before 10 Nov 2026 got the IMPORT time as their arrival time, so months-old leads showed
as brand new in My day. Put each one back on the time the form was filled (which Meta gave us and we stored).

    python scripts/repair_form_lead_times.py --tenant-slug jade-hospitainment          # dry run
    python scripts/repair_form_lead_times.py --tenant-slug jade-hospitainment --apply

Only dates the import itself wrote are changed (within 5 minutes of the import row). Prints counts only. Safe to re-run.
"""

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.models  # noqa: E402,F401
from app.core.audit import append_audit  # noqa: E402
from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.inquiry import Inquiry  # noqa: E402
from app.models.meta_form_lead import MetaFormLead  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402

NEAR = timedelta(minutes=5)


def _utc(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def _stamped_by_import(value, imported, when) -> bool:
    value = _utc(value)
    return value is not None and abs(value - imported) <= NEAR and when < value - NEAR


def repair(db, tenant_id: str, apply: bool) -> dict:
    counts = {"form_leads": 0, "leads_redated": 0, "people_redated": 0}
    rows = (
        db.query(MetaFormLead)
        .filter(MetaFormLead.tenant_id == tenant_id, MetaFormLead.status == "created")
        .filter(MetaFormLead.lead_created_at.isnot(None), MetaFormLead.inquiry_id.isnot(None))
        .order_by(MetaFormLead.lead_created_at.asc())
        .all()
    )
    for rec in rows:
        counts["form_leads"] += 1
        imported, when = _utc(rec.created_at), _utc(rec.lead_created_at)
        inquiry = db.query(Inquiry).filter_by(id=rec.inquiry_id, tenant_id=tenant_id).first()
        if inquiry is not None and _stamped_by_import(inquiry.created_at, imported, when):
            counts["leads_redated"] += 1
            if apply:
                inquiry.created_at = when
        guest = db.query(Guest).filter_by(id=rec.guest_id, tenant_id=tenant_id).first()
        if guest is not None and _stamped_by_import(guest.lead_identified_at, imported, when):
            counts["people_redated"] += 1
            if apply:
                guest.lead_identified_at = when
                if _stamped_by_import(guest.first_touch_at, imported, when):
                    guest.first_touch_at = when
    if apply and (counts["leads_redated"] or counts["people_redated"]):
        append_audit(
            db,
            tenant_id=tenant_id,
            action="meta_lead_form.times_repaired",
            target_type="tenant",
            target_id=tenant_id,
            payload={"actor": "system", "source": "repair_form_lead_times.py", **counts},
        )
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant-slug", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=a.tenant_slug).one_or_none()
        if not tenant:
            print("ERROR: unknown tenant slug")
            return 2
        set_tenant_context(db, tenant.id)
        counts = repair(db, tenant.id, a.apply)
        if a.apply:
            db.commit()
        print(("APPLIED" if a.apply else "DRY RUN (add --apply)") + f": {counts}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
