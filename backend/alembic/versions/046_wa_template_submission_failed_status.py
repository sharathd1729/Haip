"""WhatsApp module T0.3: add 'submission_failed' to TemplateStatus enum

wa_templates.status was created via create_all() (never a proper
migration, per messaging.py's own header comment) using SQLAlchemy's
default Postgres enum naming (lowercase class name: "templatestatus").
Adding a new member here so submit_template() can distinguish a genuine
Meta API failure from "awaiting review" (previously both landed on
PENDING, indistinguishable in the UI).

Revision ID: 046
Revises: 045
Create Date: 2026-07-15
"""
from alembic import op

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE templatestatus ADD VALUE IF NOT EXISTS 'submission_failed'")


def downgrade():
    # Postgres has no DROP VALUE for enums -- not reversible without
    # recreating the type. No-op, matching the pattern used elsewhere in
    # this codebase for non-reversible additive changes.
    pass
