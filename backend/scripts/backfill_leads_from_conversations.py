"""
One-off sweep: create Leads360 inquiries for WhatsApp/Instagram
conversations that existed before the chat auto-create wiring shipped
(inquiry_service.get_or_create_from_chat, wired into whatsapp.py /
process_instagram_dm.py this session).

Auto-create only fires on a conversation's first-ever message, gated by
"is this conversation new" -- pre-existing conversations never pass
through that gate, so they never got an inquiry even though they're real
leads sitting in the inbox. This script walks every tenant, finds every
WhatsApp/Instagram guest with no inquiry yet, and routes their earliest
inbound message through the same get_or_create_from_chat() logic a fresh
message would use -- landing on the identical collab/valid/default stage.

Idempotent -- safe to re-run; guests who already have an inquiry (from a
prior run of this script or from real-time auto-create) are left alone.

Run:
  cd backend && python scripts/backfill_leads_from_conversations.py [--dry-run] [--tenant-id ID]
"""

import sys
import os
import argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, set_tenant_context
from app.models.tenant import Tenant
from app.services.lead_backfill import backfill_tenant_leads_from_conversations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Roll back instead of committing")
    parser.add_argument("--tenant-id", default=None, help="Limit to a single tenant")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        tenants = (
            db.query(Tenant).filter_by(id=args.tenant_id).all()
            if args.tenant_id else db.query(Tenant).all()
        )
        print(f"Backfilling leads for {len(tenants)} tenant(s){' [dry-run]' if args.dry_run else ''}")

        totals = {"guests_processed": 0, "inquiries_created": 0, "conversations_linked": 0, "guests_skipped_no_message": 0}
        for tenant in tenants:
            set_tenant_context(db, tenant.id)
            stats = backfill_tenant_leads_from_conversations(db, tenant.id)
            print(f"  {tenant.name} ({tenant.slug}): {stats}")
            for k, v in stats.items():
                totals[k] += v

        if args.dry_run:
            db.rollback()
            print("Dry run -- rolled back, nothing committed.")
        else:
            db.commit()
            print("Committed.")

        print(f"Totals: {totals}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
