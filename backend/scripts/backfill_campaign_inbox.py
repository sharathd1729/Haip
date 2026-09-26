"""
One-off backfill: show broadcasts sent before campaign messages were written
to the inbox.

Until now a WhatsApp campaign send only wrote a row in the campaign's report,
so the template a guest received appeared nowhere in their chat. New sends
are recorded automatically; this adds the earlier ones from the report rows
(same text, send time and latest delivery status). Safe to run repeatedly:
a message already in the inbox is never added twice.

Usage (inside the API container, against production):
    docker compose -f docker-compose.prod.yml exec api \
        python3 scripts/backfill_campaign_inbox.py --tenant-slug rathaa --dry-run
    docker compose -f docker-compose.prod.yml exec api \
        python3 scripts/backfill_campaign_inbox.py --tenant-slug rathaa --apply
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, set_tenant_context
from app.models.conversation import Message
from app.models.tenant import Tenant
from app.models.wa_campaign_recipient import WACampaignRecipient as Recipient
from app.services import wa_campaign_inbox


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--campaign-id", help="limit to one campaign")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="only count what would be added")
    mode.add_argument("--apply", action="store_true", help="write the messages")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter_by(slug=args.tenant_slug).first()
        if not tenant:
            print(f"No tenant with slug={args.tenant_slug!r}", file=sys.stderr)
            return 1
        set_tenant_context(db, tenant.id)
        if args.dry_run:
            q = db.query(Recipient.wa_message_id).filter(
                Recipient.tenant_id == tenant.id, Recipient.wa_message_id.isnot(None),
                Recipient.status.in_(["sent", "delivered", "read"]))
            if args.campaign_id:
                q = q.filter(Recipient.campaign_id == args.campaign_id)
            ids = [w for (w,) in q.all()]
            there = {w for (w,) in db.query(Message.channel_message_id).filter(
                Message.tenant_id == tenant.id, Message.channel_message_id.in_(ids or [""])).all()}
            print(f"Would add {len(set(ids) - there)} message(s); {len(there)} already in the inbox.")
        else:
            print(wa_campaign_inbox.backfill(db, tenant.id, args.campaign_id))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
