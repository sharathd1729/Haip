"""dashboard_widgets table

Revision ID: 029
Revises: 028
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dashboard_widgets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("widget_key", sa.String(60), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=True),
        sa.Column("next_refresh_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now() + INTERVAL '4 hours'"), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.UniqueConstraint("tenant_id", "widget_key", name="uq_dw_tenant_widget"),
    )
    op.create_index("ix_dashboard_widgets_tenant", "dashboard_widgets", ["tenant_id"])

    op.execute("ALTER TABLE dashboard_widgets ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY dw_tenant_iso ON dashboard_widgets
        USING (tenant_id = current_setting('app.tenant_id', true)::text)
    """)


def downgrade():
    op.execute("DROP POLICY IF EXISTS dw_tenant_iso ON dashboard_widgets")
    op.drop_index("ix_dashboard_widgets_tenant", table_name="dashboard_widgets")
    op.drop_table("dashboard_widgets")
