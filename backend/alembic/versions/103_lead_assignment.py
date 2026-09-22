"""Lead assignment rules: tenant config + per-lead assignment bookkeeping

Leads auto-created from WhatsApp, Instagram and calls were never assigned --
round-robin only ran for manually added leads -- so almost every lead sat
unassigned and no agent owned it. Adds:

  tenants.lead_assignment_config   JSON, the owner's chosen method + rules
  inquiries.assigned_at            when the current owner got the lead
  inquiries.assignment_method      which rule assigned it
  inquiries.assignment_attempts    times an uncontacted lead was passed on

No new tables, so no new RLS policy; both tables already carry tenant_id
and their existing policies.

Revision ID: 103
Revises: 102
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa

revision = "103"
down_revision = "102"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tenants", sa.Column("lead_assignment_config", sa.JSON(), nullable=True))
    op.add_column("inquiries", sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("inquiries", sa.Column("assignment_method", sa.String(20), nullable=True))
    op.add_column(
        "inquiries",
        sa.Column("assignment_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    # The stale-assignment sweep scans open, auto-assigned leads by age.
    op.create_index(
        "ix_inquiries_tenant_id_assigned_at", "inquiries", ["tenant_id", "assigned_at"],
    )


def downgrade():
    op.drop_index("ix_inquiries_tenant_id_assigned_at", table_name="inquiries")
    op.drop_column("inquiries", "assignment_attempts")
    op.drop_column("inquiries", "assignment_method")
    op.drop_column("inquiries", "assigned_at")
    op.drop_column("tenants", "lead_assignment_config")
