"""
Bulk-clear a workspace's pipeline: move every lead that is not already Sold or Lost
into the tenant's Lost stage, whatever its travel dates (past, future or none).

Each move goes through inquiry_service.update_stage_by_id, so it writes the stage log, the
audit event and the ledger exactly like a person dragging the card, and nothing is deleted:
the lead, its conversations, calls and history stay and can be moved back by an owner.

Left alone: leads already in a won/lost stage, and leads in a marketing-category stage
(e.g. Collaboration Engagement), which are not sales leads.

DRY RUN BY DEFAULT. Nothing changes unless --apply is passed.

  cd backend
  python scripts/bulk_move_leads_to_lost.py --tenant-slug rathaa            # report only
  python scripts/bulk_move_leads_to_lost.py --tenant-slug rathaa --apply    # do it

In Docker on the VPS:
  docker compose -f docker-compose.prod.yml exec api python3 scripts/bulk_move_leads_to_lost.py --tenant-slug rathaa
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, set_tenant_context  # noqa: E402
from app.models.inquiry import Inquiry  # noqa: E402
from app.models.pipeline_stage import PipelineStage  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.services import inquiry_service  # noqa: E402

BATCH = 50


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant-slug", required=True, help="Workspace slug, e.g. rathaa")
    parser.add_argument("--reason", default="Bulk clear: pipeline reset requested by the owner",
                        help="Recorded on each stage change")
    parser.add_argument("--apply", action="store_true", help="Actually move the leads (default: report only)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if not tenant:
            print(f"No workspace with slug '{args.tenant_slug}'.")
            return 1
        set_tenant_context(db, tenant.id)

        stages = db.query(PipelineStage).filter_by(tenant_id=tenant.id).all()
        lost = sorted((s for s in stages if s.is_closed_lost), key=lambda s: s.order)
        if not lost:
            print("This workspace has no Lost stage (is_closed_lost). Nothing was changed.")
            return 1
        lost_stage = lost[0]
        keep_ids = {s.id for s in stages if s.is_closed_won or s.is_closed_lost or s.category == "marketing"}
        label = {s.id: s.label for s in stages}

        todo = (db.query(Inquiry)
                .filter(Inquiry.tenant_id == tenant.id, Inquiry.stage_id.notin_(keep_ids) if keep_ids else True)
                .all())
        todo = [i for i in todo if i.stage_id]            # a lead with no stage is a data anomaly: report it below
        orphans = db.query(Inquiry).filter(Inquiry.tenant_id == tenant.id, Inquiry.stage_id.is_(None)).count()
        total_all = db.query(Inquiry).filter(Inquiry.tenant_id == tenant.id).count()

        print(f"Workspace: {tenant.name} ({tenant.slug})")
        print(f"Target stage: '{lost_stage.label}'" + (f"  (note: {len(lost)} Lost stages exist, using the first)" if len(lost) > 1 else ""))
        print(f"Leads in workspace: {total_all}   to move: {len(todo)}   kept as is (Sold / Lost / marketing): {total_all - len(todo) - orphans}"
              + (f"   without a stage (skipped): {orphans}" if orphans else ""))
        for stage_id, n in sorted(Counter(i.stage_id for i in todo).items(), key=lambda kv: -kv[1]):
            print(f"  {n:>6}  {label.get(stage_id, stage_id)}")

        if not args.apply:
            print("\nDry run only, nothing changed. Add --apply to move these leads to Lost.")
            return 0
        if not todo:
            print("Nothing to do.")
            return 0

        moved = failed = 0
        for n, inquiry in enumerate(todo, start=1):
            try:
                # actor_user_id=None: audit_events.actor_user_id is a real FK to users, a made-up
                # sentinel string would violate it. Moving to a terminal stage is allowed from any
                # non-terminal stage, so the role never matters here.
                inquiry_service.update_stage_by_id(
                    db, tenant_id=tenant.id, inquiry_id=inquiry.id, new_stage_id=lost_stage.id,
                    actor_user_id=None, actor_role="system", reason=args.reason,
                )
                moved += 1
            except Exception as exc:  # noqa: BLE001 -- report and carry on; one odd lead must not stop the sweep
                db.rollback()
                set_tenant_context(db, tenant.id)
                failed += 1
                print(f"  skipped inquiry {inquiry.id}: {exc}")
                continue
            if n % BATCH == 0:
                db.commit()
                set_tenant_context(db, tenant.id)
                print(f"  ... {moved} moved")
        db.commit()
        print(f"\nDone. Moved to '{lost_stage.label}': {moved}   skipped: {failed}")
        return 0 if not failed else 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
