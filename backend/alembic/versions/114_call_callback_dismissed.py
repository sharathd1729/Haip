"""Dismiss a missed call from the call-back queue

Revision ID: 114
Revises: 113
Create Date: 2026-10-10
"""
from alembic import op

revision = "114"
down_revision = "113"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE calls ADD COLUMN IF NOT EXISTS callback_dismissed_at TIMESTAMPTZ")


def downgrade():
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS callback_dismissed_at")
