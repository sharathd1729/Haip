"""security constraints and performance indexes

Covers:
  H2  — UNIQUE partial index on messages.channel_message_id (dedup race-condition fix)
  M3  — Explicit named FK constraints for audit clarity (already enforced by SQLAlchemy
         model definitions; adding named constraints makes pg_dump / alembic diffs cleaner)
  M5  — Composite indexes on high-frequency query columns

Revision ID: 016
Revises: 015
Create Date: 2026-05-26
"""
from alembic import op
import sqlalchemy as sa

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── H2: Unique partial index on messages.channel_message_id ──────────────
    # Prevents duplicate inbound messages when Meta sends duplicate webhooks and
    # two Celery workers process them concurrently (race condition).
    # Partial because channel_message_id is NULL for internal notes.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_channel_message_id
        ON messages (channel_message_id)
        WHERE channel_message_id IS NOT NULL
    """)

    # ── M5: Performance indexes on high-frequency query columns ───────────────

    # messages.channel_message_id — fast dedup lookup
    # Already covered by the unique index above; no separate non-unique index needed.

    # messages(conversation_id, created_at) — message thread loading
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_messages_conversation_id_created_at
        ON messages (conversation_id, created_at)
    """)

    # calls(tenant_id, created_at) — call list + dashboard queries
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_calls_tenant_id_created_at
        ON calls (tenant_id, created_at)
    """)

    # guests(tenant_id, phone) — guest dedup and search
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_guests_tenant_id_phone
        ON guests (tenant_id, phone)
    """)

    # conversations(tenant_id, is_open) — inbox open/closed filter
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_conversations_tenant_id_is_open
        ON conversations (tenant_id, is_open)
    """)

    # conversations(tenant_id, last_message_at) — inbox sort by recency
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_conversations_tenant_id_last_message_at
        ON conversations (tenant_id, last_message_at DESC NULLS LAST)
    """)

    # ── M3: Named FK constraints (named for cleaner schema diffs) ────────────
    # SQLAlchemy models already enforce these via ForeignKey() declarations.
    # Adding explicit named constraints so pg_dump produces stable output and
    # alembic autogenerate doesn't flag them as missing.
    # Use DO NOTHING on conflict — safe to re-run.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_messages_conversation_id'
            ) THEN
                ALTER TABLE messages
                    ADD CONSTRAINT fk_messages_conversation_id
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                    ON DELETE CASCADE;
            END IF;
        END
        $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_calls_guest_id'
            ) THEN
                ALTER TABLE calls
                    ADD CONSTRAINT fk_calls_guest_id
                    FOREIGN KEY (guest_id) REFERENCES guests(id)
                    ON DELETE SET NULL;
            END IF;
        END
        $$;
    """)

    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_conversations_assigned_to'
            ) THEN
                ALTER TABLE conversations
                    ADD CONSTRAINT fk_conversations_assigned_to
                    FOREIGN KEY (assigned_to) REFERENCES users(id)
                    ON DELETE SET NULL;
            END IF;
        END
        $$;
    """)


def downgrade() -> None:
    # Drop named FK constraints
    op.execute("""
        ALTER TABLE conversations DROP CONSTRAINT IF EXISTS fk_conversations_assigned_to
    """)
    op.execute("""
        ALTER TABLE calls DROP CONSTRAINT IF EXISTS fk_calls_guest_id
    """)
    op.execute("""
        ALTER TABLE messages DROP CONSTRAINT IF EXISTS fk_messages_conversation_id
    """)

    # Drop indexes
    op.execute("DROP INDEX IF EXISTS ix_conversations_tenant_id_last_message_at")
    op.execute("DROP INDEX IF EXISTS ix_conversations_tenant_id_is_open")
    op.execute("DROP INDEX IF EXISTS ix_guests_tenant_id_phone")
    op.execute("DROP INDEX IF EXISTS ix_calls_tenant_id_created_at")
    op.execute("DROP INDEX IF EXISTS ix_messages_conversation_id_created_at")
    op.execute("DROP INDEX IF EXISTS uq_messages_channel_message_id")
