"""AI draft outcome tracking (HAIP_AI_Autonomy_Plan.md Phase 0, ticket 1)

Revision ID: 058
Revises: 057
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_draft_outcomes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("draft_message_id", sa.String(), sa.ForeignKey("messages.id"), nullable=False, index=True),
        sa.Column("intent", sa.String(50), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("edit_distance_pct", sa.Float(), nullable=True),
        sa.Column("time_to_action_sec", sa.Integer(), nullable=True),
        sa.Column("ai_confidence", sa.String(10), nullable=True),
        sa.Column("grounded_facts", postgresql.JSONB(), nullable=True, server_default="[]"),
        sa.Column("fact_verdict", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_ai_draft_outcomes_tenant_created", "ai_draft_outcomes", ["tenant_id", "created_at"])

    op.execute("ALTER TABLE ai_draft_outcomes ENABLE ROW LEVEL SECURITY")
    # FORCE too -- table owner would otherwise bypass the policy entirely,
    # same reasoning as migrations 053/057: this table's edit_distance_pct
    # can reveal the substance of what an agent changed in a draft, which
    # is tenant-sensitive.
    op.execute("ALTER TABLE ai_draft_outcomes FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY ai_draft_outcomes_tenant_iso ON ai_draft_outcomes
        USING (tenant_id = current_setting('app.tenant_id', true)::text)
    """)


def downgrade():
    op.drop_index("ix_ai_draft_outcomes_tenant_created", table_name="ai_draft_outcomes")
    op.drop_table("ai_draft_outcomes")
