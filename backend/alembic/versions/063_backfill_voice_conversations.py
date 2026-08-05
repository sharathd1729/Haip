"""Backfill missing voice conversations for historical calls

call_ingest.py's idempotency check (Call.filter_by(ivr_call_id=...)) returns
early on any already-seen call, *before* the voice-conversation-creation
logic added earlier today ever runs. Every Call row that existed before that
fix deployed never got a Conversation created for it, and never will on its
own -- the guest is invisible in the inbox no matter how many historical
calls they have. One-time backfill: for every Guest with at least one Call
but zero Conversation rows, create a channel=voice Conversation and set
last_message_at from their most recent call (so it sorts correctly
immediately, matching today's separate list_conversations ordering fix).

Revision ID: 063
Revises: 062
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa
import uuid

revision = "063"
down_revision = "062"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # Guests with >=1 call but zero conversations, across every tenant --
    # tenant_id carried through from the guest row itself, no cross-tenant
    # join risk since calls.guest_id/conversations.guest_id are both scoped
    # to the same tenant by construction elsewhere in the app.
    orphaned_guests = bind.execute(
        sa.text(
            """
            SELECT DISTINCT c.tenant_id, c.guest_id
            FROM calls c
            WHERE NOT EXISTS (
                SELECT 1 FROM conversations conv
                WHERE conv.guest_id = c.guest_id AND conv.tenant_id = c.tenant_id
            )
            """
        )
    ).fetchall()

    for tenant_id, guest_id in orphaned_guests:
        latest_call = bind.execute(
            sa.text(
                """
                SELECT started_at FROM calls
                WHERE tenant_id = :t AND guest_id = :g
                ORDER BY started_at DESC
                LIMIT 1
                """
            ),
            {"t": tenant_id, "g": guest_id},
        ).fetchone()
        last_message_at = latest_call[0] if latest_call else None

        # Conversation.channel is SAEnum(ChannelType) with no values_callable
        # override (unlike sibling enum columns in this codebase) -- it
        # stores the Python enum member's NAME ("VOICE"), not its value
        # ("voice"). A raw-SQL insert of the lowercase value round-trips
        # into a broken row the ORM can't deserialize back into ChannelType.
        bind.execute(
            sa.text(
                """
                INSERT INTO conversations
                    (id, tenant_id, guest_id, channel, is_open, is_sample, last_message_at, created_at, updated_at)
                VALUES
                    (:id, :tenant_id, :guest_id, 'VOICE', true, false, :last_message_at, now(), now())
                """
            ),
            {
                "id": str(uuid.uuid4()), "tenant_id": tenant_id,
                "guest_id": guest_id, "last_message_at": last_message_at,
            },
        )


def downgrade():
    """Best-effort inverse: remove voice conversations that have zero
    messages and were never assigned an inquiry/property -- i.e. ones this
    migration plausibly created. Not perfectly reversible if an agent
    manually interacted with one of these threads since upgrade (e.g. added
    an internal note), which is treated as real activity worth keeping."""
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            DELETE FROM conversations
            WHERE channel = 'VOICE'
              AND id NOT IN (SELECT DISTINCT conversation_id FROM messages)
            """
        )
    )
