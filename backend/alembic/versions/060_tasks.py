"""Task model (HAIP Inbox prototype-wiring plan, ticket 1)

Revision ID: 060
Revises: 059
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("priority", sa.String(10), nullable=False, server_default="medium"),
        sa.Column("is_done", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("guest_id", sa.String(), sa.ForeignKey("guests.id"), nullable=True),
        sa.Column("inquiry_id", sa.String(), sa.ForeignKey("inquiries.id"), nullable=True),
        sa.Column("conversation_id", sa.String(), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("assigned_to", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_tasks_tenant_assigned", "tasks", ["tenant_id", "assigned_to"])
    op.create_index("ix_tasks_tenant_guest", "tasks", ["tenant_id", "guest_id"])
    op.create_index("ix_tasks_tenant_inquiry", "tasks", ["tenant_id", "inquiry_id"])
    op.create_index("ix_tasks_tenant_conversation", "tasks", ["tenant_id", "conversation_id"])

    op.execute("ALTER TABLE tasks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tasks FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tasks_tenant_iso ON tasks
        USING (tenant_id = current_setting('app.tenant_id', true)::text)
    """)


def downgrade():
    op.drop_index("ix_tasks_tenant_conversation", table_name="tasks")
    op.drop_index("ix_tasks_tenant_inquiry", table_name="tasks")
    op.drop_index("ix_tasks_tenant_guest", table_name="tasks")
    op.drop_index("ix_tasks_tenant_assigned", table_name="tasks")
    op.drop_table("tasks")
