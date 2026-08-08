"""Ad-attribution capture for Click-to-Message leads (HAIP_Dashboard_Metrics_Plan.md Phase 1)

Revision ID: 067
Revises: 066
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

revision = "067"
down_revision = "066"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "lead_attribution",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("inquiry_id", sa.String(), sa.ForeignKey("inquiries.id"), nullable=True, index=True),
        sa.Column("conversation_id", sa.String(), sa.ForeignKey("conversations.id"), nullable=False, index=True),
        sa.Column("guest_id", sa.String(), sa.ForeignKey("guests.id"), nullable=False, index=True),
        sa.Column("destination_channel", sa.String(20), nullable=False),
        sa.Column("ad_id", sa.String(60), nullable=True),
        sa.Column("adset_id", sa.String(60), nullable=True),
        sa.Column("campaign_id", sa.String(60), nullable=True),
        sa.Column("ctwa_clid", sa.String(255), nullable=True),
        sa.Column("source_type", sa.String(20), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("headline", sa.String(500), nullable=True),
        sa.Column("media_type", sa.String(20), nullable=True),
        sa.Column("raw_referral", sa.JSON(), nullable=True),
        sa.Column("first_message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_lead_attribution_tenant_ad", "lead_attribution", ["tenant_id", "ad_id"])
    op.create_index("ix_lead_attribution_tenant_channel", "lead_attribution", ["tenant_id", "destination_channel"])
    op.create_index("ix_lead_attribution_tenant_first_msg", "lead_attribution", ["tenant_id", "first_message_at"])
    # Idempotency guard -- a replayed/retried webhook for the same
    # conversation's first message must never create a second row.
    op.create_index(
        "ix_lead_attribution_tenant_conversation_unique",
        "lead_attribution", ["tenant_id", "conversation_id"], unique=True,
    )

    op.execute("ALTER TABLE lead_attribution ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE lead_attribution FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY lead_attribution_tenant_iso ON lead_attribution
        USING (tenant_id = current_setting('app.tenant_id', true)::text)
    """)


def downgrade():
    op.drop_index("ix_lead_attribution_tenant_conversation_unique", table_name="lead_attribution")
    op.drop_index("ix_lead_attribution_tenant_first_msg", table_name="lead_attribution")
    op.drop_index("ix_lead_attribution_tenant_channel", table_name="lead_attribution")
    op.drop_index("ix_lead_attribution_tenant_ad", table_name="lead_attribution")
    op.drop_table("lead_attribution")
