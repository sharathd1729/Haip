"""IVR call routing tables

Revision ID: 026
Revises: 025
Create Date: 2026-06-11

Creates:
  - ivr_configs    (one per tenant, SIP credentials + greeting config)
  - ivr_options    (DTMF digit → transfer number)
  - ivr_call_logs  (per-call routing decision log)

All tables: tenant_id column + RLS policy.
"""
import sqlalchemy as sa
from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect as _inspect
    bind = op.get_bind()
    existing = _inspect(bind).get_table_names()

    if "ivr_configs" not in existing:
        op.create_table(
            "ivr_configs",
            sa.Column("id",                     sa.String(36),   primary_key=True),
            sa.Column("tenant_id",              sa.String(36),   nullable=False),
            sa.Column("greeting_text",          sa.String(1000), nullable=False),
            sa.Column("language",               sa.String(10),   nullable=False, server_default="en-IN"),
            sa.Column("sip_credentials_enc",    sa.LargeBinary,  nullable=True),
            sa.Column("dograh_workflow_id",     sa.String(255),  nullable=True),
            sa.Column("dograh_phone_number_id", sa.String(255),  nullable=True),
            sa.Column("business_hours_enabled", sa.Boolean,      nullable=False, server_default="false"),
            sa.Column("business_hours",         sa.JSON,         nullable=True),
            sa.Column("is_active",              sa.Boolean,      nullable=False, server_default="true"),
            sa.Column("created_at",  sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at",  sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_ivr_configs_tenant_id", "ivr_configs", ["tenant_id"], unique=True)
        op.execute("""
            ALTER TABLE ivr_configs ENABLE ROW LEVEL SECURITY;
            CREATE POLICY ivr_configs_tenant_isolation ON ivr_configs
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
        """)

    if "ivr_options" not in existing:
        op.create_table(
            "ivr_options",
            sa.Column("id",            sa.String(36),  primary_key=True),
            sa.Column("tenant_id",     sa.String(36),  nullable=False),
            sa.Column("ivr_config_id", sa.String(36),  sa.ForeignKey("ivr_configs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("digit",         sa.Integer,     nullable=False),
            sa.Column("label",         sa.String(100), nullable=False),
            sa.Column("spoken_text",   sa.String(500), nullable=False),
            sa.Column("route_number",  sa.String(20),  nullable=False),
            sa.Column("department",    sa.String(100), nullable=True),
            sa.Column("created_at",    sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at",    sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("ix_ivr_options_config_id", "ivr_options", ["ivr_config_id"])
        op.create_index("ix_ivr_options_tenant_id", "ivr_options", ["tenant_id"])
        op.create_unique_constraint(
            "uq_ivr_options_config_digit", "ivr_options", ["ivr_config_id", "digit"]
        )
        op.execute("""
            ALTER TABLE ivr_options ENABLE ROW LEVEL SECURITY;
            CREATE POLICY ivr_options_tenant_isolation ON ivr_options
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
        """)

    if "ivr_call_logs" not in existing:
        op.create_table(
            "ivr_call_logs",
            sa.Column("id",                   sa.String(36),  primary_key=True),
            sa.Column("tenant_id",            sa.String(36),  nullable=False),
            sa.Column("call_id",              sa.String(36),  sa.ForeignKey("calls.id", ondelete="SET NULL"), nullable=True),
            sa.Column("dograh_call_id",       sa.String(255), nullable=True),
            sa.Column("digit_pressed",        sa.Integer,     nullable=True),
            sa.Column("routed_to_department", sa.String(100), nullable=True),
            sa.Column("duration_seconds",     sa.Integer,     nullable=False, server_default="0"),
            sa.Column("caller_phone_token",   sa.String(64),  nullable=True),
            sa.Column("called_at",            sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_ivr_call_logs_tenant_called_at", "ivr_call_logs", ["tenant_id", "called_at"]
        )
        op.execute("""
            ALTER TABLE ivr_call_logs ENABLE ROW LEVEL SECURITY;
            CREATE POLICY ivr_call_logs_tenant_isolation ON ivr_call_logs
                USING (tenant_id = current_setting('app.tenant_id', true)::text);
        """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ivr_call_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS ivr_options CASCADE")
    op.execute("DROP TABLE IF EXISTS ivr_configs CASCADE")
