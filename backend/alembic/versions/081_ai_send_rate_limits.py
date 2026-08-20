"""Rate limits on autonomous AI sends.

Without a cap, a message loop (an auto-responder on the guest's side, a
webhook redelivery storm, or simply a bad prompt that keeps prompting a
reply) can send a guest a dozen messages in a minute. On a luxury brand's
WhatsApp line that is worse than the bot being silent.

Adds `messages.sent_autonomously` because autonomous sends were previously
indistinguishable from human-approved ones -- `was_approved=True` is set by
the inbox approve handler, the one-click action, AND the auto-send path, so
there was no way to count "messages the AI sent by itself". That gap also
meant autonomous sends were invisible to the ai_draft_outcomes trust
metrics.

Revision ID: 081
Revises: 080
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa

revision = "081"
down_revision = "080"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "messages",
        sa.Column("sent_autonomously", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    # Supports the per-conversation hourly count on the hot path.
    op.create_index(
        "ix_messages_autonomous_recent",
        "messages",
        ["conversation_id", "sent_autonomously", "created_at"],
    )
    op.create_index(
        "ix_messages_tenant_autonomous_recent",
        "messages",
        ["tenant_id", "sent_autonomously", "created_at"],
    )

    # Per-tenant tunables. Defaults are deliberately conservative: a genuine
    # conversation rarely needs more than a handful of AI replies an hour,
    # and anything beyond that is far more likely to be a loop than a
    # engaged guest.
    op.add_column("tenants", sa.Column(
        "ai_max_sends_per_conversation_hour", sa.Integer(), nullable=False, server_default="6"))
    op.add_column("tenants", sa.Column(
        "ai_max_consecutive_replies", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("tenants", sa.Column(
        "ai_max_sends_per_tenant_hour", sa.Integer(), nullable=False, server_default="60"))


def downgrade():
    op.drop_column("tenants", "ai_max_sends_per_tenant_hour")
    op.drop_column("tenants", "ai_max_consecutive_replies")
    op.drop_column("tenants", "ai_max_sends_per_conversation_hour")
    op.drop_index("ix_messages_tenant_autonomous_recent", table_name="messages")
    op.drop_index("ix_messages_autonomous_recent", table_name="messages")
    op.drop_column("messages", "sent_autonomously")
