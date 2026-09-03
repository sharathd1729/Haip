"""One open conversation per guest+channel -- close a real race condition.

Confirmed live: process_instagram_dm.py and whatsapp.py both do a plain
"query for an open conversation, create one if none found" with no locking.
Two webhook deliveries for the same guest arriving within milliseconds of
each other (confirmed: two Instagram messages 100ms apart) can both see "no
open conversation" and both create one -- the guest's messages then split
across two "twin" conversations, only one of which ever gets linked to an
inquiry (inquiry-linking only fires on is_new_conversation). Downstream
effects confirmed live: generate_ai_summary.py only ever sees the
inquiry-linked conversation's messages, silently missing whatever the guest
said in the orphan twin -- in the one real case found, that was the
message with the guest's actual travel dates and guest count, which then
never appeared anywhere in Leads360.

A partial unique index makes this a hard DB constraint instead of a
race-prone application-level check -- the two call sites are updated in the
same change to catch the resulting IntegrityError and re-query the row the
other concurrent insert just won, rather than crashing the webhook handler.

Revision ID: 099
Revises: 098
Create Date: 2026-09-03
"""
from alembic import op
import sqlalchemy as sa

revision = "099"
down_revision = "098"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_conversations_one_open_per_guest_channel"


def upgrade() -> None:
    conn = op.get_bind()
    existing = [
        r[0] for r in conn.execute(sa.text(
            "SELECT indexname FROM pg_indexes WHERE indexname = :name"
        ), {"name": INDEX_NAME})
    ]
    if existing:
        return

    # Real duplicates found before this migration must be resolved first --
    # the index create fails otherwise. Merge each duplicate group into the
    # single conversation that already carries an inquiry_id (or, if none
    # of them do, the oldest one), moving every message across and closing
    # the rest. Rare in practice (confirmed live: 1 guest, tenant-wide) but
    # must be handled generically, not just for the one guest already found.
    dupes = conn.execute(sa.text("""
        SELECT tenant_id, guest_id, channel, array_agg(id ORDER BY
            (inquiry_id IS NOT NULL) DESC, created_at ASC) AS ids
        FROM conversations
        WHERE is_open = true
        GROUP BY tenant_id, guest_id, channel
        HAVING COUNT(*) > 1
    """)).fetchall()
    for tenant_id, guest_id, channel, ids in dupes:
        survivor_id = ids[0]
        for orphan_id in ids[1:]:
            conn.execute(sa.text(
                "UPDATE messages SET conversation_id = :survivor WHERE conversation_id = :orphan"
            ), {"survivor": survivor_id, "orphan": orphan_id})
            conn.execute(sa.text(
                "UPDATE conversations SET is_open = false WHERE id = :orphan"
            ), {"orphan": orphan_id})

    op.create_index(
        INDEX_NAME, "conversations", ["tenant_id", "guest_id", "channel"],
        unique=True, postgresql_where=sa.text("is_open = true"),
    )


def downgrade() -> None:
    conn = op.get_bind()
    existing = [
        r[0] for r in conn.execute(sa.text(
            "SELECT indexname FROM pg_indexes WHERE indexname = :name"
        ), {"name": INDEX_NAME})
    ]
    if existing:
        op.drop_index(INDEX_NAME, table_name="conversations")
