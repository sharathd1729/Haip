"""
Reopen specific leads that are sitting in a Lost stage, by guest phone number: move each guest's
most recent lead back to an open stage (Active by default).

Goes through inquiry_service.reopen_lost_inquiry, so it writes the stage log, ledger event and
audit entry like any other move and clears the lost reason. Only leads currently in Lost are
touched; a Sold lead is never reopened.

DRY RUN BY DEFAULT. Nothing changes unless --apply is passed.

  cd backend
  python scripts/reopen_lost_leads.py --tenant-slug rathaa --phone 9742077710 --phone 9886171706
  python scripts/reopen_lost_leads.py --tenant-slug rathaa --phone 9742077710 --phone 9886171706 --apply
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import or_  # noqa: E402

from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.guest_identity import GuestIdentity  # noqa: E402
from app.models.inquiry import Inquiry  # noqa: E402
from app.models.pipeline_stage import PipelineStage  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services import inquiry_service  # noqa: E402


def _digits(raw: str) -> str:
    d = re.sub(r"\D", "", raw or "")
    return d[-10:] if len(d) >= 10 else d


def _mask(phone: str) -> str:
    d = re.sub(r"\D", "", phone or "")
    return f"******{d[-4:]}" if d else "(no phone)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--phone", action="append", required=True, help="Guest phone (any format); repeat for several")
    parser.add_argument("--stage", default="active", help="Stage key to reopen into (default: active)")
    parser.add_argument("--reason", default="Reopened by the owner: still an active conversation",
                        help="Recorded on the stage change")
    parser.add_argument("--apply", action="store_true", help="Actually reopen (default: report only)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if not tenant:
            print(f"No workspace with slug '{args.tenant_slug}'.")
            return 1
        set_tenant_context(db, tenant.id)
        target = db.query(PipelineStage).filter_by(tenant_id=tenant.id, key=args.stage).first()
        if not target:
            print(f"No stage with key '{args.stage}' in this workspace.")
            return 1
        stage_by_id = {s.id: s for s in db.query(PipelineStage).filter_by(tenant_id=tenant.id).all()}
        print(f"Workspace: {tenant.name}   reopen into: '{target.label}'")

        failed = 0
        changed = 0
        for raw in args.phone:
            digits = _digits(raw)
            if len(digits) < 10:
                print(f"\n{raw}: not a full phone number, skipped.")
                failed += 1
                continue
            ids = {g.id for g in db.query(Guest.id, Guest.phone).filter(
                Guest.tenant_id == tenant.id, Guest.is_deleted.is_(False), Guest.phone.like(f"%{digits}")).all()}
            ids |= {r[0] for r in db.query(GuestIdentity.guest_id).filter(
                GuestIdentity.tenant_id == tenant.id, GuestIdentity.identity_value.like(f"%{digits}")).all()}
            print(f"\nPhone ending {digits[-4:]}:")
            if not ids:
                print("  no guest in this workspace has that number (the lead may have no phone on file).")
                failed += 1
                continue
            for gid in sorted(ids):
                guest = db.query(Guest).filter_by(id=gid, tenant_id=tenant.id).first()
                inquiry = (db.query(Inquiry).filter_by(tenant_id=tenant.id, guest_id=gid)
                           .order_by(Inquiry.created_at.desc()).first())
                who = f"{guest.name or 'Unnamed'} ({_mask(guest.phone)})"
                if not inquiry:
                    print(f"  {who}: no lead.")
                    continue
                cur = stage_by_id.get(inquiry.stage_id)
                print(f"  {who}: lead {inquiry.id} is in '{cur.label if cur else 'no stage'}'")
                if not cur or not cur.is_closed_lost:
                    print("    not in Lost, left as is.")
                    continue
                if not args.apply:
                    print(f"    would move to '{target.label}'")
                    continue
                inquiry_service.reopen_lost_inquiry(
                    db, tenant_id=tenant.id, inquiry_id=inquiry.id, new_stage_id=target.id,
                    actor_user_id=None, actor_role="system", reason=args.reason)
                db.commit()
                set_tenant_context(db, tenant.id)
                changed += 1
                print(f"    moved to '{target.label}'")

        print("\n" + (f"Done. Reopened: {changed}" if args.apply else "Dry run only, nothing changed. Add --apply to reopen."))
        return 0 if not failed else 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
