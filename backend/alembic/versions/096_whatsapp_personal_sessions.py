"""Personal/Business-app WhatsApp bridge sessions (Phase 1: read-only capture).

An agent pairs their own personal WhatsApp (or the WhatsApp Business app --
not the official Cloud API) via QR code through the whatsmeow-based bridge
service, so guest conversations on that number still get tracked in HAIP's
Inbox/Leads360. One row per agent, not per tenant.

Revision ID: 096
Revises: 095
Create Date: 2026-09-02
"""
from alembic import op
import sqlalchemy as sa

revision = "096"
down_revision = "095"
branch_labels = None
depends_on = None


def _table_exists(table: str) -> bool:
    conn = op.get_bind()
    return sa.inspect(conn).has_table(table)


def upgrade() -> None:
    if _table_exists("whatsapp_personal_sessions"):
        return

    op.create_table(
        "whatsapp_personal_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column(
            "status", sa.String(20), nullable=False,
            server_default="pending_pairing",
        ),
        sa.Column("phone_number", sa.String(32), nullable=True),
        sa.Column("device_jid", sa.String(255), nullable=True),
        sa.Column("webhook_secret_enc", sa.LargeBinary(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_qr_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_wa_personal_session_user"),
    )
    op.create_index("ix_wa_personal_sessions_tenant", "whatsapp_personal_sessions", ["tenant_id"])

    # RLS -- every tenant-scoped table gets one (CLAUDE.md, non-negotiable).
    op.execute("ALTER TABLE whatsapp_personal_sessions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE whatsapp_personal_sessions FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY whatsapp_personal_sessions_tenant_iso ON whatsapp_personal_sessions
        USING (tenant_id = current_setting('app.tenant_id', true)::text)
    """)


def downgrade() -> None:
    if not _table_exists("whatsapp_personal_sessions"):
        return
    op.execute("DROP POLICY IF EXISTS whatsapp_personal_sessions_tenant_iso ON whatsapp_personal_sessions")
    op.execute("ALTER TABLE whatsapp_personal_sessions NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE whatsapp_personal_sessions DISABLE ROW LEVEL SECURITY")
    op.drop_table("whatsapp_personal_sessions")
