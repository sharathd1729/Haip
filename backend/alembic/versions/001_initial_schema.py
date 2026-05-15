"""Initial HAIP schema — all 14 entities

Revision ID: 001
Revises:
Create Date: 2026-05-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\"")

    # ── tenants ──────────────────────────────────────────────────────────────
    op.create_table(
        "tenants",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("plan", sa.String(50), nullable=False, server_default="growth"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("data_region", sa.String(20), nullable=False, server_default="ap-south-1"),
        sa.Column("ivr_provider", sa.String(50)),
        sa.Column("ivr_config", postgresql.JSONB, server_default="{}"),
        sa.Column("whatsapp_phone_number_id", sa.String(100)),
        sa.Column("whatsapp_config", postgresql.JSONB, server_default="{}"),
        sa.Column("brand_name", sa.String(255)),
        sa.Column("brand_config", postgresql.JSONB, server_default="{}"),
        sa.Column("monthly_call_limit", sa.String),
        sa.Column("monthly_wa_limit", sa.String),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"])

    # ── users ─────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(20)),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255)),
        sa.Column("role", sa.String(50), nullable=False, server_default="concierge"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_mfa_enabled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("google_id", sa.String(255)),
        sa.Column("microsoft_id", sa.String(255)),
        sa.Column("property_scope", postgresql.JSONB, server_default="[]"),
        sa.Column("notification_prefs", postgresql.JSONB, server_default="{}"),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_users_email", "users", ["email"])

    # ── refresh_tokens ────────────────────────────────────────────────────────
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("user_id", sa.String, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("tenant_id", sa.String, nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("is_revoked", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"])

    # ── properties ────────────────────────────────────────────────────────────
    op.create_table(
        "properties",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("type", sa.String(50), server_default="villa"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("address", sa.Text),
        sa.Column("city", sa.String(100)),
        sa.Column("state", sa.String(100)),
        sa.Column("country", sa.String(10), server_default="IN"),
        sa.Column("lat", sa.Numeric(9, 6)),
        sa.Column("lng", sa.Numeric(9, 6)),
        sa.Column("max_adults", sa.Integer, server_default="2"),
        sa.Column("max_children", sa.Integer, server_default="0"),
        sa.Column("bedrooms", sa.Integer, server_default="1"),
        sa.Column("bathrooms", sa.Integer, server_default="1"),
        sa.Column("ivr_virtual_number", sa.String(20)),
        sa.Column("ivr_flow_id", sa.String(100)),
        sa.Column("hostaway_listing_id", sa.String(100)),
        sa.Column("airbnb_listing_id", sa.String(100)),
        sa.Column("amenities", postgresql.JSONB, server_default="[]"),
        sa.Column("photos", postgresql.JSONB, server_default="[]"),
        sa.Column("description", sa.Text),
        sa.Column("brand_voice", sa.Text),
        sa.Column("faqs", postgresql.JSONB, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_properties_tenant_id", "properties", ["tenant_id"])

    # ── guests ────────────────────────────────────────────────────────────────
    op.create_table(
        "guests",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("email", sa.String(255)),
        sa.Column("name", sa.String(255)),
        sa.Column("alt_phone", sa.String(20)),
        sa.Column("city", sa.String(100)),
        sa.Column("nationality", sa.String(100)),
        sa.Column("language_pref", sa.String(10), server_default="en"),
        sa.Column("vip_tier", sa.String(20)),
        sa.Column("total_stays", sa.Integer, server_default="0"),
        sa.Column("total_inquiries", sa.Integer, server_default="0"),
        sa.Column("lifetime_value", sa.Numeric(12, 2), server_default="0"),
        sa.Column("predicted_csat", sa.Numeric(3, 2)),
        sa.Column("last_contact_at", sa.String),
        sa.Column("tags", postgresql.JSONB, server_default="[]"),
        sa.Column("preferences", postgresql.JSONB, server_default="{}"),
        sa.Column("marketing_consent", sa.Boolean, server_default="false"),
        sa.Column("recording_consent", sa.Boolean, server_default="true"),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("is_deleted", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_guests_tenant_id", "guests", ["tenant_id"])
    op.create_index("ix_guests_phone", "guests", ["phone"])
    op.create_unique_constraint("uq_guests_tenant_phone", "guests", ["tenant_id", "phone"])

    # ── inquiries ─────────────────────────────────────────────────────────────
    op.create_table(
        "inquiries",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("guest_id", sa.String, sa.ForeignKey("guests.id"), nullable=False),
        sa.Column("property_id", sa.String, sa.ForeignKey("properties.id")),
        sa.Column("assigned_to", sa.String, sa.ForeignKey("users.id")),
        sa.Column("stage", sa.String(30), nullable=False, server_default="new"),
        sa.Column("source", sa.String(50)),
        sa.Column("lost_reason", sa.String(50)),
        sa.Column("lost_note", sa.Text),
        sa.Column("check_in", sa.String),
        sa.Column("check_out", sa.String),
        sa.Column("adults", sa.Integer),
        sa.Column("children", sa.Integer),
        sa.Column("occasion", sa.String(100)),
        sa.Column("budget", sa.Numeric(12, 2)),
        sa.Column("currency", sa.String(3), server_default="INR"),
        sa.Column("quoted_amount", sa.Numeric(12, 2)),
        sa.Column("quoted_at", sa.String),
        sa.Column("quote_pdf_url", sa.Text),
        sa.Column("first_response_at", sa.String),
        sa.Column("sla_breached", sa.Boolean, server_default="false"),
        sa.Column("ai_summary", sa.Text),
        sa.Column("ai_next_action", sa.Text),
        sa.Column("ai_confidence", sa.Numeric(3, 2)),
        sa.Column("tags", postgresql.JSONB, server_default="[]"),
        sa.Column("custom_fields", postgresql.JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_inquiries_tenant_id", "inquiries", ["tenant_id"])
    op.create_index("ix_inquiries_guest_id", "inquiries", ["guest_id"])
    op.create_index("ix_inquiries_stage", "inquiries", ["stage"])

    # ── conversations ─────────────────────────────────────────────────────────
    op.create_table(
        "conversations",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("guest_id", sa.String, sa.ForeignKey("guests.id"), nullable=False),
        sa.Column("inquiry_id", sa.String, sa.ForeignKey("inquiries.id")),
        sa.Column("property_id", sa.String, sa.ForeignKey("properties.id")),
        sa.Column("assigned_to", sa.String, sa.ForeignKey("users.id")),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("channel_conversation_id", sa.String(255)),
        sa.Column("is_open", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("first_response_at", sa.String),
        sa.Column("last_message_at", sa.String),
        sa.Column("sla_breached", sa.Boolean, server_default="false"),
        sa.Column("ai_mode", sa.String(20), server_default="shadow"),
        sa.Column("ai_draft", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_conversations_tenant_id", "conversations", ["tenant_id"])
    op.create_index("ix_conversations_guest_id", "conversations", ["guest_id"])

    # ── messages ──────────────────────────────────────────────────────────────
    op.create_table(
        "messages",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, nullable=False),
        sa.Column("conversation_id", sa.String, sa.ForeignKey("conversations.id"), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("body", sa.Text),
        sa.Column("media_url", sa.Text),
        sa.Column("media_type", sa.String(50)),
        sa.Column("channel_message_id", sa.String(255)),
        sa.Column("channel_status", sa.String(50)),
        sa.Column("is_ai_generated", sa.Boolean, server_default="false"),
        sa.Column("ai_confidence", sa.String(10)),
        sa.Column("was_approved", sa.Boolean),
        sa.Column("sender_id", sa.String, sa.ForeignKey("users.id")),
        sa.Column("sender_name", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_channel_message_id", "messages", ["channel_message_id"])

    # ── calls ─────────────────────────────────────────────────────────────────
    op.create_table(
        "calls",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("guest_id", sa.String, sa.ForeignKey("guests.id")),
        sa.Column("inquiry_id", sa.String, sa.ForeignKey("inquiries.id")),
        sa.Column("agent_id", sa.String, sa.ForeignKey("users.id")),
        sa.Column("property_id", sa.String, sa.ForeignKey("properties.id")),
        sa.Column("ivr_provider", sa.String(50), nullable=False),
        sa.Column("ivr_call_id", sa.String(255), nullable=False, unique=True),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("from_number", sa.String(20), nullable=False),
        sa.Column("to_number", sa.String(20), nullable=False),
        sa.Column("duration_seconds", sa.Integer, server_default="0"),
        sa.Column("started_at", sa.String),
        sa.Column("ended_at", sa.String),
        sa.Column("recording_url_ivr", sa.Text),
        sa.Column("recording_s3_key", sa.Text),
        sa.Column("recording_fetched", sa.Boolean, server_default="false"),
        sa.Column("transcription_status", sa.String(20), server_default="pending"),
        sa.Column("ai_score_status", sa.String(20), server_default="pending"),
        sa.Column("transcript", postgresql.JSONB),
        sa.Column("ai_summary", sa.Text),
        sa.Column("ai_disposition", sa.String(20)),
        sa.Column("ai_next_action", sa.Text),
        sa.Column("ai_score", sa.Numeric(5, 2)),
        sa.Column("human_disposition", sa.String(20)),
        sa.Column("disposition_note", sa.Text),
        sa.Column("disposition_set_by", sa.String),
        sa.Column("transcription_cost_usd", sa.Numeric(8, 4), server_default="0"),
        sa.Column("llm_cost_usd", sa.Numeric(8, 4), server_default="0"),
        sa.Column("storage_cost_usd", sa.Numeric(8, 4), server_default="0"),
        sa.Column("detected_language", sa.String(10)),
        sa.Column("is_code_mixed", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_calls_tenant_id", "calls", ["tenant_id"])
    op.create_index("ix_calls_ivr_call_id", "calls", ["ivr_call_id"])
    op.create_index("ix_calls_guest_id", "calls", ["guest_id"])

    # ── rate_plans ────────────────────────────────────────────────────────────
    op.create_table(
        "rate_plans",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, nullable=False),
        sa.Column("property_id", sa.String, sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("base_price_per_night", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(3), server_default="INR"),
        sa.Column("min_nights", sa.Integer, server_default="1"),
        sa.Column("max_nights", sa.Integer),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("seasonal_pricing", postgresql.JSONB, server_default="[]"),
        sa.Column("inclusions", postgresql.JSONB, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── stays ─────────────────────────────────────────────────────────────────
    op.create_table(
        "stays",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, nullable=False),
        sa.Column("guest_id", sa.String, sa.ForeignKey("guests.id"), nullable=False),
        sa.Column("property_id", sa.String, sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("inquiry_id", sa.String, sa.ForeignKey("inquiries.id")),
        sa.Column("check_in", sa.String, nullable=False),
        sa.Column("check_out", sa.String, nullable=False),
        sa.Column("adults", sa.Integer, server_default="1"),
        sa.Column("children", sa.Integer, server_default="0"),
        sa.Column("status", sa.String(30), server_default="confirmed"),
        sa.Column("total_amount", sa.Numeric(12, 2)),
        sa.Column("currency", sa.String(3), server_default="INR"),
        sa.Column("special_requests", postgresql.JSONB, server_default="[]"),
        sa.Column("dietary_requirements", postgresql.JSONB, server_default="[]"),
        sa.Column("occasion", sa.String(100)),
        sa.Column("hostaway_booking_id", sa.String(100)),
        sa.Column("channel_source", sa.String(50)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_stays_guest_id", "stays", ["guest_id"])
    op.create_index("ix_stays_property_id", "stays", ["property_id"])

    # ── rubrics ───────────────────────────────────────────────────────────────
    op.create_table(
        "rubrics",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("version", sa.String(20), server_default="1.0"),
        sa.Column("is_default", sa.Boolean, server_default="false"),
        sa.Column("criteria", postgresql.JSONB, nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── call_scores ───────────────────────────────────────────────────────────
    op.create_table(
        "call_scores",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, nullable=False),
        sa.Column("call_id", sa.String, sa.ForeignKey("calls.id"), nullable=False),
        sa.Column("rubric_id", sa.String, sa.ForeignKey("rubrics.id"), nullable=False),
        sa.Column("rubric_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("total_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("max_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("percentage", sa.Numeric(5, 2), nullable=False),
        sa.Column("has_auto_fail", sa.Boolean, server_default="false"),
        sa.Column("criterion_scores", postgresql.JSONB, nullable=False),
        sa.Column("model_used", sa.String(50), nullable=False),
        sa.Column("ai_confidence", sa.Numeric(3, 2)),
        sa.Column("processing_time_ms", sa.String),
        sa.Column("is_overridden", sa.Boolean, server_default="false"),
        sa.Column("override_scores", postgresql.JSONB),
        sa.Column("override_reason", sa.Text),
        sa.Column("overridden_by", sa.String, sa.ForeignKey("users.id")),
        sa.Column("overridden_at", sa.String),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_call_scores_call_id", "call_scores", ["call_id"])

    # ── consent_log (append-only) ─────────────────────────────────────────────
    op.create_table(
        "consent_log",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("tenant_id", sa.String, nullable=False),
        sa.Column("guest_id", sa.String, sa.ForeignKey("guests.id")),
        sa.Column("consent_type", sa.String(50), nullable=False),
        sa.Column("granted", sa.Boolean, nullable=False),
        sa.Column("source", sa.String(50)),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("audit_id", sa.String),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── embeddings (pgvector) ─────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            namespace TEXT NOT NULL,
            ref_id TEXT NOT NULL,
            ref_type TEXT NOT NULL,
            embedding vector(1536),
            content TEXT,
            metadata JSONB DEFAULT '{}',
            created_at TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_embeddings_tenant_ns ON embeddings (tenant_id, namespace)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_embeddings_vec ON embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)")


def downgrade() -> None:
    op.drop_table("call_scores")
    op.drop_table("rubrics")
    op.drop_table("stays")
    op.drop_table("rate_plans")
    op.drop_table("calls")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("inquiries")
    op.drop_table("guests")
    op.drop_table("properties")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
    op.drop_table("tenants")
    op.drop_table("consent_log")
    op.drop_table("embeddings")
