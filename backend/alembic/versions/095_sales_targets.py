"""Sales targets: monthly revenue goals per tenant / property / agent.

Backs the Targets & Pick-Up module. Only the MONTHLY figure is stored --
daily targets are derived (monthly / days_in_month) in targets_service so
the two can never drift apart.

Actual revenue is not stored here; it is read from `stays` at query time.
The agent attribution path already exists in the codebase:
inquiry_service creates a Stay with inquiry_id set when a lead reaches a
closed-won stage, and Inquiry.assigned_to is the agent.

Revision ID: 095
Revises: 094
Create Date: 2026-08-30
"""
from alembic import op
import sqlalchemy as sa

revision = "095"
down_revision = "094"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    conn = op.get_bind()
    return sa.inspect(conn).has_table(table)


def upgrade() -> None:
    if _table_exists("sales_targets"):
        return

    op.create_table(
        "sales_targets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_id", sa.String(), nullable=True),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("target_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "scope_type", "scope_id", "period_month",
            name="uq_sales_target_scope_month",
        ),
    )
    op.create_index("ix_sales_targets_scope_id", "sales_targets", ["scope_id"])
    op.create_index("ix_sales_targets_tenant_month", "sales_targets", ["tenant_id", "period_month"])

    # RLS -- every tenant-scoped table gets one (CLAUDE.md, non-negotiable).
    op.execute("ALTER TABLE sales_targets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sales_targets FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY sales_targets_tenant_iso ON sales_targets
        USING (tenant_id = current_setting('app.tenant_id', true)::text)
    """)


def downgrade() -> None:
    if not _table_exists("sales_targets"):
        return
    op.execute("DROP POLICY IF EXISTS sales_targets_tenant_iso ON sales_targets")
    op.execute("ALTER TABLE sales_targets NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE sales_targets DISABLE ROW LEVEL SECURITY")
    op.drop_table("sales_targets")
