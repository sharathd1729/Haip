"""
One-off: lead-form leads imported before form leads got an Inbox thread have none. Give each its "Facebook" thread
(the form's answers as a staff note), exactly as a new form lead gets now.

    python scripts/backfill_form_lead_threads.py --tenant-slug jade-hospitainment          # dry run
    python scripts/backfill_form_lead_threads.py --tenant-slug jade-hospitainment --apply

A person who already has a thread on any channel is skipped. Prints counts only. Safe to re-run.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.models  # noqa: E402,F401
from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.conversation import Conversation  # noqa: E402
from app.models.inquiry import Inquiry  # noqa: E402
from app.models.meta_form_lead import MetaFormLead  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services.meta_lead_forms_service import open_thread  # noqa: E402


def backfill(db, tenant_id: str, apply: bool) -> dict:
    counts = {"form_leads": 0, "threads_made": 0, "already_have_a_thread": 0}
    rows = (
        db.query(MetaFormLead)
        .filter(
            MetaFormLead.tenant_id == tenant_id, MetaFormLead.guest_id.isnot(None), MetaFormLead.inquiry_id.isnot(None)
        )
        .order_by(MetaFormLead.lead_created_at.asc())
        .all()
    )
    seen: set[str] = set()
    for rec in rows:
        counts["form_leads"] += 1
        has = (
            rec.guest_id in seen
            or db.query(Conversation.id).filter_by(tenant_id=tenant_id, guest_id=rec.guest_id).first()
        )
        if has:
            counts["already_have_a_thread"] += 1
            continue
        seen.add(rec.guest_id)
        counts["threads_made"] += 1
        if apply:
            inquiry = db.query(Inquiry).filter_by(id=rec.inquiry_id, tenant_id=tenant_id).first()
            if inquiry is not None:
                open_thread(db, tenant_id, rec, inquiry)
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
        counts = backfill(db, tenant.id, a.apply)
        if a.apply:
            db.commit()
        print(("APPLIED" if a.apply else "DRY RUN (add --apply)") + f": {counts}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
