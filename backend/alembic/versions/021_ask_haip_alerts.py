"""Ask HAIP alerts — threshold monitoring table

Revision ID: 021
Revises: 020
Create Date: 2026-05-30

Adds:
  - ask_haip_alerts — saved threshold alerts (e.g. "notify if revenue < ₹5L")
"""
from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ask_haip_alerts",
        sa.Column("id",           sa.String,   primary_key=True),
        sa.Column("tenant_id",    sa.String,   nullable=False, index=True),
        sa.Column("user_id",      sa.String,   nullable=True),
        sa.Column("name",         sa.String(255), nullable=False),
        sa.Column("metric",       sa.String(100), nullable=False),  # revenue_mtd | occupancy_pct | high_risk_count
        sa.Column("operator",     sa.String(10),  nullable=False),  # lt | gt | lte | gte
        sa.Column("threshold",    sa.Numeric(15, 2), nullable=False),
        sa.Column("is_active",    sa.Boolean,  default=True),
        sa.Column("notify_email", sa.Boolean,  default=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger_count", sa.Integer, default=0),
        sa.Column("created_at",   sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at",   sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ask_haip_alerts_tenant", "ask_haip_alerts", ["tenant_id"])
    op.create_index("ix_ask_haip_alerts_active", "ask_haip_alerts", ["is_active"])


def downgrade() -> None:
    op.drop_table("ask_haip_alerts")
