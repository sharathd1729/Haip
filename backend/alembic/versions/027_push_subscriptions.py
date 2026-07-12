"""push_subscriptions table

Revision ID: 027
Revises: 026
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("SET LOCAL app.tenant_id = 'migration'")

    from alembic import op as _op
    from sqlalchemy import inspect as _inspect
    bind = _op.get_bind()
    if "push_subscriptions" in _inspect(bind).get_table_names():
        return  # table already exists — skip (idempotent)

    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("endpoint", sa.String(), nullable=False),
        sa.Column("p256dh", sa.String(), nullable=False),
        sa.Column("auth", sa.String(), nullable=False),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.UniqueConstraint("user_id", "endpoint", name="uq_push_user_endpoint"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )

    op.create_index(
        "ix_push_subscriptions_tenant_user",
        "push_subscriptions",
        ["tenant_id", "user_id"],
    )

    # Row-level security
    op.execute("ALTER TABLE push_subscriptions ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY push_subscriptions_tenant_isolation
        ON push_subscriptions
        USING (tenant_id = current_setting('app.tenant_id', true)::text)
    """)


def downgrade():
    op.execute("DROP POLICY IF EXISTS push_subscriptions_tenant_isolation ON push_subscriptions")
    op.drop_index("ix_push_subscriptions_tenant_user", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
