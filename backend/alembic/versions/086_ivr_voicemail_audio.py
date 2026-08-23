"""Second IVR audio slot: voicemail prompt, played when no agent answers
(and, per the tenant's business_hours, when nobody's even attempted --
see webhooks_vobiz.py's answer webhook). Same shape as the existing
ivr_greeting_audio_key column added in migration 084.

Revision ID: 086
Revises: 085
Create Date: 2026-08-23
"""
from alembic import op
import sqlalchemy as sa

revision = "086"
down_revision = "085"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tenants", sa.Column("ivr_voicemail_audio_key", sa.String(500), nullable=True))


def downgrade():
    op.drop_column("tenants", "ivr_voicemail_audio_key")
