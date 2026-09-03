"""
One-off sweep: promote inquiries that are stuck in the tenant's default
(invalid-category) pipeline stage even though the guest has already shared
a phone/email/WhatsApp number -- the same promotion process_instagram_dm.py
now runs live when a phone lands mid-conversation (see that fix's commit),
applied retroactively to leads that got stuck before the fix shipped.

Confirmed live case: lead_auto_create.py only ever routes an inquiry's
entry stage once, at creation time. A guest whose first message had no
phone landed in the default entry stage (e.g. "Unqualified"); if they
shared their number in a later message, nothing re-evaluated the stage --
the lead stayed stuck there forever, invisible to the "Shared their
details" dashboard widget (which only counts valid-category stages) no
matter how high-intent it actually was.

Only promotes an inquiry that is CURRENTLY sitting in the tenant's
is_default_entry stage -- a lead an agent already moved further (Active,
Unsuitable, ...) is left alone, same guard as the live fix.

Run:
  cd backend && python scripts/backfill_stuck_default_stage_leads.py [--tenant-id ID] [--dry-run]

Always run --dry-run first and read the output before the real pass.
"""

import sys
import os
import argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.tenant import Tenant
from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.models.guest_identity import GuestIdentity
from app.services import worklist_service, inquiry_service


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", default=None, help="Limit to one tenant (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        tenant_q = db.query(Tenant.id, Tenant.name)
        if args.tenant_id:
            tenant_q = tenant_q.filter(Tenant.id == args.tenant_id)

        total_promoted = 0
        for tenant_id, tenant_name in tenant_q.all():
            default_stage = (
                db.query(PipelineStage)
                .filter_by(tenant_id=tenant_id, is_default_entry=True)
                .first()
            )
            valid_stage = (
                db.query(PipelineStage)
                .filter_by(tenant_id=tenant_id, is_valid_lead_entry=True)
                .first()
            )
            if not default_stage or not valid_stage:
                continue  # tenant hasn't been seeded with the Leads360 taxonomy

            stuck_inquiries = (
                db.query(Inquiry)
                .filter(Inquiry.tenant_id == tenant_id, Inquiry.stage_id == default_stage.id)
                .all()
            )
            if not stuck_inquiries:
                continue

            guest_ids = {i.guest_id for i in stuck_inquiries}
            guests_with_contact = {
                r[0] for r in db.query(GuestIdentity.guest_id)
                .filter(
                    GuestIdentity.tenant_id == tenant_id,
                    GuestIdentity.guest_id.in_(guest_ids),
                    GuestIdentity.identity_type.in_(worklist_service.CONTACT_IDENTITY_TYPES),
                ).all()
            }

            for inquiry in stuck_inquiries:
                if inquiry.guest_id not in guests_with_contact:
                    continue
                print(f"  [{tenant_name}] {'[dry-run] would promote' if args.dry_run else 'promoting'} "
                      f"inquiry={inquiry.id} guest={inquiry.guest_id} "
                      f"'{default_stage.label}' -> '{valid_stage.label}'")
                if not args.dry_run:
                    inquiry_service.update_stage_by_id(
                        db, tenant_id=tenant_id, inquiry_id=inquiry.id,
                        new_stage_id=valid_stage.id,
                        actor_user_id="system", actor_role="system",
                        reason="Backfill: guest had already shared contact details",
                    )
                    db.commit()
                total_promoted += 1

        print(f"Done. {'Would promote' if args.dry_run else 'Promoted'}: {total_promoted}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
