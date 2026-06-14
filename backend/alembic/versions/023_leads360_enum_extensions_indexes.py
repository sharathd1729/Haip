"""Leads360 — InquirySource/InquiryStage enum extensions + performance indexes

Revision ID: 023
Revises: 022
Create Date: 2026-05-31

Changes:
  - inquirysource enum: add inbound_call, outbound_call, ota_mmt,
                             ota_goibibo, channel_manager, web_chat
  - inquirystage enum:  add site_visit_scheduled, site_visit_done
  - 4 new composite indexes on inquiries for Leads360 pipeline query
  - NOTE: ALTER TYPE ADD VALUE cannot run inside a transaction on PostgreSQL.
    This migration sets transaction_per_migration = False.
"""
from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None

# Required: ALTER TYPE ADD VALUE cannot run inside a transaction
transaction_per_migration = False


def upgrade() -> None:
    # ── InquirySource new values ──────────────────────────────────────────────
    op.execute("ALTER TYPE inquirysource ADD VALUE IF NOT EXISTS 'inbound_call'")
    op.execute("ALTER TYPE inquirysource ADD VALUE IF NOT EXISTS 'outbound_call'")
    op.execute("ALTER TYPE inquirysource ADD VALUE IF NOT EXISTS 'ota_mmt'")
    op.execute("ALTER TYPE inquirysource ADD VALUE IF NOT EXISTS 'ota_goibibo'")
    op.execute("ALTER TYPE inquirysource ADD VALUE IF NOT EXISTS 'channel_manager'")
    op.execute("ALTER TYPE inquirysource ADD VALUE IF NOT EXISTS 'web_chat'")

    # ── InquiryStage new values ───────────────────────────────────────────────
    op.execute("ALTER TYPE inquirystage ADD VALUE IF NOT EXISTS 'site_visit_scheduled'")
    op.execute("ALTER TYPE inquirystage ADD VALUE IF NOT EXISTS 'site_visit_done'")

    # ── Performance indexes for Leads360 pipeline query ───────────────────────
    op.create_index(
        "ix_inquiries_tenant_id_stage",
        "inquiries",
        ["tenant_id", "stage"],
    )
    op.create_index(
        "ix_inquiries_tenant_id_source",
        "inquiries",
        ["tenant_id", "source"],
    )
    op.create_index(
        "ix_inquiries_tenant_id_assigned_to",
        "inquiries",
        ["tenant_id", "assigned_to"],
    )
    op.create_index(
        "ix_inquiries_tenant_id_updated_at",
        "inquiries",
        ["tenant_id", "updated_at"],
    )


def downgrade() -> None:
    # Drop indexes (safe to run inside transaction)
    op.drop_index("ix_inquiries_tenant_id_stage", table_name="inquiries")
    op.drop_index("ix_inquiries_tenant_id_source", table_name="inquiries")
    op.drop_index("ix_inquiries_tenant_id_assigned_to", table_name="inquiries")
    op.drop_index("ix_inquiries_tenant_id_updated_at", table_name="inquiries")

    # PostgreSQL does not support removing enum values without recreating the type.
    # Downgrade leaves the enum values in place — they are harmless and unused.
    # To fully revert, recreate the enum type without the added values (complex,
    # requires no rows referencing the new values). Left as no-op for safety.
