"""AI safety controls: kill switch + escalation keywords.

Two gaps that must close before autonomous mode is defensible:

  - There was no way to stop the AI other than killing the Celery worker.
    A kill switch is the control an owner reaches for when the bot says
    something wrong to a guest, and it has to work in one click, instantly,
    without a deploy.

  - `complaint` was a recognised concierge intent that received no special
    routing at all -- a guest saying "this is unacceptable, I want a refund"
    was eligible for the same autonomous reply as "what time is check-in".

Kill switch forces shadow rather than off: drafting still helps the agents,
it just stops anything reaching a guest unreviewed.

Revision ID: 080
Revises: 079
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "080"
down_revision = "079"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tenants",
        sa.Column("ai_kill_switch", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("tenants", sa.Column("ai_kill_switch_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tenants", sa.Column("ai_kill_switch_by", sa.String(), nullable=True))
    op.add_column("tenants", sa.Column("ai_kill_switch_reason", sa.String(500), nullable=True))
    # Tenant-specific additions on top of the built-in defaults. Never a
    # replacement -- the defaults cover refunds/legal/safety and a tenant
    # must not be able to accidentally delete those by clearing a field.
    op.add_column(
        "tenants",
        sa.Column("ai_escalation_keywords", postgresql.JSONB(), nullable=True, server_default="[]"),
    )


def downgrade():
    op.drop_column("tenants", "ai_escalation_keywords")
    op.drop_column("tenants", "ai_kill_switch_reason")
    op.drop_column("tenants", "ai_kill_switch_by")
    op.drop_column("tenants", "ai_kill_switch_at")
    op.drop_column("tenants", "ai_kill_switch")
