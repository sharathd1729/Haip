"""Per-channel AI concierge mode settings for WhatsApp.

Instagram already had `ig_ai_mode_default` / `ig_ai_confidence_threshold`
(migration 042). WhatsApp had no equivalent at all -- whatsapp.py hardcoded
`ai_mode="shadow"` at conversation creation, and concierge_draft.py read the
*Instagram* threshold for WhatsApp drafts too. The Settings > AI Concierge
screen offered a WhatsApp mode selector with nothing behind it.

Revision ID: 079
Revises: 078
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa

revision = "079"
down_revision = "078"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tenants",
        sa.Column("wa_ai_mode_default", sa.String(20), nullable=False, server_default="shadow"),
    )
    op.add_column(
        "tenants",
        sa.Column("wa_ai_confidence_threshold", sa.Float(), nullable=False, server_default="0.78"),
    )


def downgrade():
    op.drop_column("tenants", "wa_ai_confidence_threshold")
    op.drop_column("tenants", "wa_ai_mode_default")
