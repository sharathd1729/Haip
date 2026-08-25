"""Staff avatar photos. Same shape as the existing ivr_greeting_audio_key
column (migration 084) -- a fixed S3 key, presigned on read via
media_storage.get_presigned_media_url. Guest avatars stay initials-only
(no self-service mechanism for guests to supply a photo) -- this is
staff (users table) only.

Revision ID: 090
Revises: 089
Create Date: 2026-08-25
"""
from alembic import op
import sqlalchemy as sa

revision = "090"
down_revision = "089"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("avatar_s3_key", sa.String(500), nullable=True))


def downgrade():
    op.drop_column("users", "avatar_s3_key")
