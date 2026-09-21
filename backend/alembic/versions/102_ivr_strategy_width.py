"""IVR: widen tenants.ivr_routing_strategy to 40 characters

tenants.ivr_routing_strategy was VARCHAR(20) (migration 084), but the
"sticky_agent_parallel" strategy is 21 characters. Postgres rejected every
save of it ("value too long"), so the option in Settings -> IVR could never
be selected -- the radio snapped back on every click. SQLite (tests)
doesn't enforce VARCHAR length, which is why the suite never caught it.

Revision ID: 102
Revises: 101
Create Date: 2026-09-21
"""
from alembic import op
import sqlalchemy as sa

revision = "102"
down_revision = "101"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "tenants", "ivr_routing_strategy",
        type_=sa.String(40), existing_type=sa.String(20),
        existing_nullable=False, existing_server_default="single",
    )


def downgrade():
    # A tenant on a >20-char strategy must be moved off it first or the
    # ALTER fails -- fall them back to plain parallel ringing.
    op.execute(
        "UPDATE tenants SET ivr_routing_strategy = 'parallel' "
        "WHERE length(ivr_routing_strategy) > 20"
    )
    op.alter_column(
        "tenants", "ivr_routing_strategy",
        type_=sa.String(20), existing_type=sa.String(40),
        existing_nullable=False, existing_server_default="single",
    )
