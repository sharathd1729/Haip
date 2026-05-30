"""Analytics: insights table + Postgres materialized view stubs

Revision ID: 018
Revises: 017
Create Date: 2026-05-30

Creates:
  - insights table (AI-generated proactive alerts)

Postgres materialized views are defined as comments below.
They are created automatically by the refresh_analytics Celery task on first run.
SQLite (used in tests) skips mat-view creation gracefully.
"""
from alembic import op
import sqlalchemy as sa

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "insights",
        sa.Column("id",            sa.String(),    primary_key=True, nullable=False),
        sa.Column("tenant_id",     sa.String(),    nullable=False),
        sa.Column("category_code", sa.String(10),  nullable=False),
        sa.Column("target_id",     sa.String(),    nullable=True),
        sa.Column("category",      sa.String(20),  nullable=False),
        sa.Column("severity",      sa.String(10),  nullable=False, server_default="medium"),
        sa.Column("title",         sa.String(255), nullable=False),
        sa.Column("body",          sa.Text(),      nullable=True),
        sa.Column("cta_label",     sa.String(100), nullable=True),
        sa.Column("cta_href",      sa.String(500), nullable=True),
        sa.Column("is_dismissed",      sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("dismissed_by",      sa.String(),  nullable=True),
        sa.Column("dismissed_at",      sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_auto_resolved",  sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("auto_resolved_at",  sa.DateTime(timezone=True), nullable=True),
        sa.Column("data_snapshot", sa.JSON(),     nullable=True),
        sa.Column("expires_at",    sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at",    sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at",    sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index("ix_insights_tenant_id",     "insights", ["tenant_id"])
    op.create_index("ix_insights_category_code", "insights", ["category_code"])
    op.create_index("ix_insights_is_dismissed",  "insights", ["is_dismissed"])

    # Unique constraint for idempotent upsert: one active insight per detector per target
    op.create_index(
        "uq_insights_tenant_category_target",
        "insights",
        ["tenant_id", "category_code", "target_id"],
        unique=False,  # Not unique — dismissed ones stay; use application-level upsert
    )

    # ── Postgres materialized views (skipped on SQLite) ──────────────────────
    # These are created/refreshed by the refresh_analytics Celery task.
    # Shown here for documentation only.
    #
    # mv_daily_occupancy:
    #   SELECT d::date AS date, s.tenant_id, s.property_id,
    #          COUNT(DISTINCT s.id) FILTER (WHERE s.status IN ('confirmed','checked_in')) AS booked_stays,
    #          SUM(s.total_amount) FILTER (WHERE s.status IN ('confirmed','checked_in')) AS revenue_locked
    #   FROM generate_series(...) d
    #   JOIN stays s ON d BETWEEN s.check_in::date AND (s.check_out::date - 1)
    #   GROUP BY date, s.tenant_id, s.property_id;
    #
    # mv_inquiry_funnel_daily:
    #   SELECT created_at::date AS date, tenant_id, source, stage, COUNT(*) AS count,
    #          COUNT(*) FILTER (WHERE sla_breached) AS sla_breached_count
    #   FROM inquiries GROUP BY date, tenant_id, source, stage;
    #
    # mv_agent_daily_stats:
    #   SELECT started_at::date AS date, tenant_id, agent_id,
    #          COUNT(*) AS calls_count, AVG(ai_score) AS avg_qa_score
    #   FROM calls WHERE agent_id IS NOT NULL
    #   GROUP BY date, tenant_id, agent_id;


def downgrade() -> None:
    op.drop_index("uq_insights_tenant_category_target", table_name="insights")
    op.drop_index("ix_insights_is_dismissed",  table_name="insights")
    op.drop_index("ix_insights_category_code", table_name="insights")
    op.drop_index("ix_insights_tenant_id",     table_name="insights")
    op.drop_table("insights")
