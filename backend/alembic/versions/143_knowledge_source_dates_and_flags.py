"""Knowledge entries: when the source published them, and review flags.

* ``knowledge_entries.source_published_at`` -- an Instagram post's timestamp or an ad's start date (the passage's real date, shown to
  the concierge so newer content wins over older content on the same topic).
* ``knowledge_entries.content_flags`` -- machine flags for the reviewer (``mentions_price``, ``mentions_offer``).

Additive, nullable, no data change. Production builds tables with create_all at startup, and create_all never adds a column to a
table that already exists (see 128), so both statements are ``ADD COLUMN IF NOT EXISTS``. The table already has RLS (078).

Revision ID: 143
Revises: 142
Create Date: 2026-10-18
"""
from alembic import op

revision = "143"
down_revision = "142"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE knowledge_entries ADD COLUMN IF NOT EXISTS source_published_at TIMESTAMPTZ NULL")
    op.execute("ALTER TABLE knowledge_entries ADD COLUMN IF NOT EXISTS content_flags JSON NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE knowledge_entries DROP COLUMN IF EXISTS content_flags")
    op.execute("ALTER TABLE knowledge_entries DROP COLUMN IF EXISTS source_published_at")
