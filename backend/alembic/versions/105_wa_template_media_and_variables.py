"""WhatsApp templates: header media and campaign variable mapping

wa_templates.header_media_key -- storage key of the image/video/PDF header.
wa_campaigns.variable_map     -- how each template {{n}} is filled per recipient.

wa_templates / wa_campaigns came from create_all() in production and from
migration 017 on a fresh database, so both may or may not already have these
columns: ADD COLUMN IF NOT EXISTS covers both. Existing rows keep NULL, which
is what "no media" / "no variables mapped" already means. RLS on both tables
was set up in 017 and is unaffected by new columns.

Revision ID: 105
Revises: 104
Create Date: 2026-09-25
"""
from alembic import op

revision = "105"
down_revision = "104"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE wa_templates ADD COLUMN IF NOT EXISTS header_media_key VARCHAR(500)")
    op.execute("ALTER TABLE wa_campaigns ADD COLUMN IF NOT EXISTS variable_map JSON")


def downgrade():
    op.execute("ALTER TABLE wa_campaigns DROP COLUMN IF EXISTS variable_map")
    op.execute("ALTER TABLE wa_templates DROP COLUMN IF EXISTS header_media_key")
