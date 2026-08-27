"""wa_subscribers.guest_id — link WhatsApp subscribers to Guest

Context: WASubscriber (the campaign/broadcast audience + VIP-tag list) has
always been matched to Guest purely by exact phone-string equality
(flow_engine.py's is_vip check, automation_engine.py's tag_guest action) --
no FK, no join. Guest.phone is normalized to E.164 by normalize_phone()
(guest_service.py); WASubscriber.phone was stored exactly as typed, with no
normalization at all -- so a VIP tag or campaign audience filter silently
failed to match a real guest whenever the subscriber's number wasn't typed
in exact "+91XXXXXXXXXX" form.

This adds a real guest_id link, resolved (best-effort) at write time in
upsert_subscriber via the same normalize_phone() lookup Guest already uses,
so matching stops depending on incidental string formatting.

Revision ID: 091
Revises: 090
Create Date: 2026-08-27
"""
from alembic import op
import sqlalchemy as sa

revision = "091"
down_revision = "090"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'wa_subscribers' AND column_name = 'guest_id'
            ) THEN
                ALTER TABLE wa_subscribers ADD COLUMN guest_id TEXT REFERENCES guests(id);
            END IF;
        END
        $$
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_wa_subscribers_guest_id ON wa_subscribers (guest_id)
    """)
    # Best-effort backfill for existing rows: match on exact phone equality
    # only (safe — normalize_phone() isn't callable from raw SQL). Rows that
    # don't match exactly stay NULL and get re-attempted the next time that
    # subscriber is upserted through the app, which now normalizes on write.
    op.execute("""
        UPDATE wa_subscribers s
        SET guest_id = g.id
        FROM guests g
        WHERE s.guest_id IS NULL
          AND g.tenant_id = s.tenant_id
          AND g.phone = s.phone
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_wa_subscribers_guest_id")
    op.execute("ALTER TABLE wa_subscribers DROP COLUMN IF EXISTS guest_id")
