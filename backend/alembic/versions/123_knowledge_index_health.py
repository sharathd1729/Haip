"""Knowledge base: indexing health (attempt counter) and out-of-date marker.

``embedding_attempts``  consecutive failed indexing attempts, so the periodic sweep can back off and stop instead of
                        retrying a permanently failing entry forever.
``stale_since``         set when a re-crawl / re-upload of the same page or file no longer contains the passage; such an
                        entry is not retrieved until the owner chooses to keep it.

Additive and idempotent: two columns on an existing table (metadata-only on PostgreSQL 11+), nothing dropped or rewritten.

Revision ID: 123
Revises: 122
"""
from alembic import op

revision = "123"
down_revision = "122"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute("ALTER TABLE knowledge_entries ADD COLUMN IF NOT EXISTS embedding_attempts INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE knowledge_entries ADD COLUMN IF NOT EXISTS stale_since TIMESTAMPTZ")


def downgrade():
    op.execute("ALTER TABLE knowledge_entries DROP COLUMN IF EXISTS stale_since")
    op.execute("ALTER TABLE knowledge_entries DROP COLUMN IF EXISTS embedding_attempts")
