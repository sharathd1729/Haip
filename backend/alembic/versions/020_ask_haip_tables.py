"""Ask HAIP: sessions, findings, and reports tables

Revision ID: 020
Revises: 019
Create Date: 2026-05-30

Adds:
  - ask_haip_sessions  — per-question session with intent + paths
  - ask_haip_findings  — cached RCA results (1hr TTL)
  - ask_haip_reports   — generated reports with delivery tracking
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── ask_haip_sessions ───────────────────────────────────────────────────
    op.create_table(
        "ask_haip_sessions",
        sa.Column("id",              sa.String,         primary_key=True),
        sa.Column("tenant_id",       sa.String,         nullable=False, index=True),
        sa.Column("user_id",         sa.String,         nullable=True),
        sa.Column("question",        sa.Text,           nullable=False),
        sa.Column("intent_json",     sa.JSON,           nullable=True),
        sa.Column("paths_generated", sa.JSON,           nullable=True),
        sa.Column("range_days",      sa.Integer,        default=30),
        sa.Column("property_ids",    sa.JSON,           nullable=True),  # list[str]
        sa.Column("created_at",      sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at",      sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ask_haip_sessions_tenant", "ask_haip_sessions", ["tenant_id"])

    # ── ask_haip_findings ───────────────────────────────────────────────────
    op.create_table(
        "ask_haip_findings",
        sa.Column("id",             sa.String,   primary_key=True),
        sa.Column("tenant_id",      sa.String,   nullable=False, index=True),
        sa.Column("session_id",     sa.String,   sa.ForeignKey("ask_haip_sessions.id"), nullable=True),
        sa.Column("question_hash",  sa.String(64), nullable=False),
        sa.Column("findings_json",  sa.JSON,     nullable=True),
        sa.Column("agents_used",    sa.JSON,     nullable=True),  # list[str]
        sa.Column("range_days",     sa.Integer,  nullable=True),
        sa.Column("property_ids",   sa.JSON,     nullable=True),
        sa.Column("confidence",     sa.Numeric(3, 2), nullable=True),
        sa.Column("created_at",     sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at",     sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ask_haip_findings_tenant",   "ask_haip_findings", ["tenant_id"])
    op.create_index("ix_ask_haip_findings_hash",     "ask_haip_findings", ["question_hash"])

    # ── ask_haip_reports ────────────────────────────────────────────────────
    op.create_table(
        "ask_haip_reports",
        sa.Column("id",            sa.String,  primary_key=True),
        sa.Column("tenant_id",     sa.String,  nullable=False, index=True),
        sa.Column("report_type",   sa.String(30), nullable=False),
        sa.Column("period_start",  sa.String(10), nullable=True),  # YYYY-MM-DD
        sa.Column("period_end",    sa.String(10), nullable=True),
        sa.Column("title",         sa.String(255), nullable=True),
        sa.Column("html_content",  sa.Text,    nullable=True),
        sa.Column("pdf_s3_key",    sa.Text,    nullable=True),
        sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at",    sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ask_haip_reports_tenant", "ask_haip_reports", ["tenant_id"])
    op.create_index("ix_ask_haip_reports_type",   "ask_haip_reports", ["report_type"])


def downgrade() -> None:
    op.drop_table("ask_haip_reports")
    op.drop_table("ask_haip_findings")
    op.drop_table("ask_haip_sessions")
