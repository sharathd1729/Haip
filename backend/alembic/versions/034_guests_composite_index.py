"""Add composite index for guest list query

Revision ID: 034
Revises: 033
Create Date: 2026-07-11

Investigated all high-traffic tables (calls, conversations, messages,
inquiries, guests) for missing composite indexes. Most turned out to
already be covered by earlier migrations:
  - calls: ix_calls_tenant_id_created_at (016), ix_calls_tenant_id_started_at (017)
  - conversations: ix_conversations_tenant_id_last_message_at,
                    ix_conversations_tenant_id_is_open (016)
  - messages: ix_messages_conversation_id_created_at (016)
  - inquiries: ix_inquiries_tenant_id_{stage,source,assigned_to,updated_at} (023)

The one genuine gap: GET /guests filters by (tenant_id, is_deleted) and
sorts by created_at (app/api/v1/endpoints/guests.py:25-32) with no
supporting composite index.
"""
from alembic import op

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_guests_tenant_id_deleted_created_at",
        "guests",
        ["tenant_id", "is_deleted", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_guests_tenant_id_deleted_created_at", table_name="guests")
