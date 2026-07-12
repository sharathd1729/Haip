"""008 inquiry current_stage_entered_at + saved_replies table

Revision ID: 008
Revises: 007
Create Date: 2026-05-19
"""
from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def _column_exists(table: str, col: str) -> bool:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    return col in {c["name"] for c in insp.get_columns(table)}


def _table_exists(table: str) -> bool:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    return table in insp.get_table_names()


def upgrade():
    # K5 — track when an inquiry entered its current stage
    if not _column_exists("inquiries", "current_stage_entered_at"):
        op.add_column(
            "inquiries",
            sa.Column("current_stage_entered_at", sa.DateTime(timezone=True), nullable=True),
        )

    # W3 — saved replies (canned responses)
    if not _table_exists("saved_replies"):
        op.create_table(
            "saved_replies",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
            sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("language", sa.String(10), server_default="en"),
            sa.Column("usage_count", sa.Integer(), server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
        )

        # RLS
        conn = op.get_bind()
        dialect = conn.dialect.name
        if dialect == "postgresql":
            op.execute("ALTER TABLE saved_replies ENABLE ROW LEVEL SECURITY")
            op.execute(
                "CREATE POLICY saved_replies_isolation ON saved_replies "
                "USING (tenant_id = current_setting('app.tenant_id', true)::text)"
            )


def downgrade():
    op.drop_table("saved_replies")
    op.drop_column("inquiries", "current_stage_entered_at")
