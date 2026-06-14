"""Automation rules and runs tables

Revision ID: 024
Revises: 023
Create Date: 2026-06-04

Creates:
  - automation_rules  (rule definitions per tenant)
  - automation_runs   (execution log per rule firing)
"""
import sqlalchemy as sa
from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as _inspect
    bind = op.get_bind()
    existing = _inspect(bind).get_table_names()
    if "automation_rules" in existing:
        return  # already applied via create_all — skip
    # ── automation_rules ──────────────────────────────────────────────────────
    op.create_table(
        "automation_rules",
        sa.Column("id",             sa.String(36),  primary_key=True),
        sa.Column("tenant_id",      sa.String(36),  nullable=False, index=True),
        sa.Column("name",           sa.String(255), nullable=False),
        sa.Column("description",    sa.String(500), nullable=True),
        sa.Column("trigger",        sa.String(100), nullable=False),
        sa.Column("trigger_config", sa.JSON,        nullable=True, server_default="{}"),
        sa.Column("action",         sa.String(100), nullable=False),
        sa.Column("action_config",  sa.JSON,        nullable=True, server_default="{}"),
        sa.Column("is_active",      sa.Boolean,     nullable=False, server_default="true"),
        sa.Column("run_count",      sa.Integer,     nullable=False, server_default="0"),
        sa.Column("last_run_at",    sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at",     sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at",     sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )
    op.create_index("ix_automation_rules_tenant_active", "automation_rules", ["tenant_id", "is_active"])

    # ── automation_runs ───────────────────────────────────────────────────────
    op.create_table(
        "automation_runs",
        sa.Column("id",               sa.String(36),  primary_key=True),
        sa.Column("tenant_id",        sa.String(36),  nullable=False, index=True),
        sa.Column("automation_id",    sa.String(36),  sa.ForeignKey("automation_rules.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("automation_name",  sa.String(255), nullable=True),   # denormalised for fast display
        sa.Column("status",           sa.String(20),  nullable=False),  # success | failed | skipped
        sa.Column("trigger_event",    sa.String(100), nullable=True),
        sa.Column("context",          sa.JSON,        nullable=True, server_default="{}"),
        sa.Column("detail",           sa.String(500), nullable=True),
        sa.Column("error",            sa.Text,        nullable=True),
        sa.Column("ran_at",           sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_automation_runs_tenant_ran_at", "automation_runs", ["tenant_id", "ran_at"])


def downgrade() -> None:
    op.drop_table("automation_runs")
    op.drop_table("automation_rules")
