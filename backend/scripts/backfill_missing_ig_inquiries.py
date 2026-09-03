"""
One-off sweep: create the Inquiry that should have existed all along for
every Instagram conversation with a real, substantive first inbound
message but no inquiry_id -- confirmed live root cause: process_instagram_dm.py
gated lead-auto-create on is_new_conversation (true exactly once, on the
conversation's literal first message). A guest whose opener was a shared
post/reel (body="[ig_post]", excluded by its own leading "[" check) or
whose first message otherwise didn't qualify got is_new_conversation=True
on that excluded message and False on every message after -- so no
inquiry was ever created, no matter what they said next. Fixed going
forward in the same commit as this script; this is the retroactive half.

Uses the exact same routing lead_auto_create.py already applies to every
new lead (collab-keyword match -> collab stage; phone in text -> valid
lead entry stage; otherwise -> default/invalid entry stage) via
inquiry_service.get_or_create_from_chat(), so a backfilled inquiry lands
on the identical stage a live message would have produced at the time.

Only touches conversations whose first qualifying inbound message (real
text, not an attachment/share marker) still has no inquiry_id -- leaves
alone conversations with genuinely no text (pure media/reel-share only,
nothing to route from) and the unrelated VOICE-channel rows (different
code path, call-ingest, not this bug).

Run:
  cd backend && python scripts/backfill_missing_ig_inquiries.py [--tenant-id ID] [--dry-run]

Always run --dry-run first and read the output before the real pass.

Real bug, caught live after the first real run of this script: the
created inquiries all landed with created_at="now" (get_or_create_from_chat's
default, correct for a live message, wrong here) instead of the date the
guest actually sent the qualifying message -- 348 inquiries backdated up
to 7 weeks all showed as "created today," inflating every last-24h
dashboard metric until caught and corrected by hand. Fixed here: the
inquiry's created_at/current_stage_entered_at are set to the qualifying
message's own created_at right after creation.
"""

import sys
import os
import argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.conversation import Conversation, Message, ChannelType, MessageDirection


def _first_qualifying_message(db, conversation_id: str, tenant_id: str):
    """Earliest inbound message with real, substantive text -- mirrors the
    exact `body and not body.startswith("[")` check process_instagram_dm.py
    applies live. Returns (body, created_at)."""
    rows = (
        db.query(Message.body, Message.created_at)
        .filter(
            Message.tenant_id == tenant_id,
            Message.conversation_id == conversation_id,
            Message.direction == MessageDirection.INBOUND,
        )
        .order_by(Message.created_at.asc())
        .all()
    )
    for body, created_at in rows:
        if body and not body.startswith("["):
            return body, created_at
    return None, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", default=None, help="Limit to one tenant (default: all)")
    parser.add_argument("--dry-run", action="store_true", help="Report what would be created without writing")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        from app.services.inquiry_service import get_or_create_from_chat
        from app.models.inquiry import InquirySource

        convs_q = db.query(Conversation).filter(
            Conversation.channel == ChannelType.INSTAGRAM,
            Conversation.inquiry_id.is_(None),
        )
        if args.tenant_id:
            convs_q = convs_q.filter(Conversation.tenant_id == args.tenant_id)
        conversations = convs_q.all()
        print(f"Scanning {len(conversations)} Instagram conversation(s) with no inquiry_id")

        created = 0
        skipped_no_text = 0
        for conv in conversations:
            body, message_at = _first_qualifying_message(db, conv.id, conv.tenant_id)
            if not body:
                skipped_no_text += 1
                continue

            print(f"  {'[dry-run] would create' if args.dry_run else 'creating'} inquiry "
                  f"conversation={conv.id} guest={conv.guest_id} "
                  f"dated {message_at} from: {body[:70]!r}")
            if not args.dry_run:
                lead_inquiry = get_or_create_from_chat(
                    db, conv.tenant_id, conv.guest_id,
                    source=InquirySource.META_IG.value, message_text=body,
                )
                conv.inquiry_id = lead_inquiry.id
                if message_at:
                    lead_inquiry.created_at = message_at
                    lead_inquiry.current_stage_entered_at = message_at
                db.commit()
            created += 1

        print(f"Done. {'Would create' if args.dry_run else 'Created'}: {created}, "
              f"skipped (no real text to route from): {skipped_no_text}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
