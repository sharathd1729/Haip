"""Merge Ask a manager (168, agent_consults) with the CRM lead reporting columns (169, inquiries.lead_type + validation).

feat/agent-consult (168) and fix/crm-lead-lists (169) both hang off 167, so landing both leaves two heads; this revision joins
them. It changes no schema.

Revision ID: 170
Revises: 168, 169
"""
revision = "170"
down_revision = ("168", "169")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
