from sqlalchemy import Column, String, Boolean, JSON, Integer, LargeBinary, Float, DateTime
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import TimestampMixin, gen_uuid


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    plan = Column(String(50), default="growth", nullable=False)  # starter/growth/scale/enterprise
    is_active = Column(Boolean, default=True, nullable=False)
    # Chosen at signup; drives per-type nav/dashboard gating (e.g. caravan
    # tenants don't see Properties / Rate Calculator / Channel Manager /
    # AI Concierge). Nullable: pre-existing tenants until backfilled.
    business_type = Column(String(30), nullable=True)  # caravan / villa_resort / homestay / hotel
    data_region = Column(String(20), default="ap-south-1", nullable=False)

    # IVR config
    ivr_provider = Column(String(50), nullable=True)  # callerdesk / acefone / mcube / vobiz
    ivr_config = Column(JSON, default=dict)

    # WhatsApp config
    whatsapp_phone_number_id = Column(String(100), nullable=True)
    whatsapp_config = Column(JSON, default=dict)

    # Brand config
    brand_name = Column(String(255), nullable=True)
    brand_config = Column(JSON, default=dict)

    # Limits (overrides plan defaults)
    monthly_call_limit = Column(String, nullable=True)
    monthly_wa_limit = Column(String, nullable=True)

    # K14: round-robin assignment state
    last_assigned_user_id = Column(String, nullable=True)

    # B10: per-tenant timezone + business hours
    timezone = Column(String(60), default="Asia/Kolkata", nullable=False)
    # business_hours: dict keyed by weekday 0-6 (Mon-Sun), each {"open": "HH:MM", "close": "HH:MM", "closed": bool}
    business_hours = Column(JSON, default=dict, nullable=False)

    # M5: LLM Router — optional per-tenant provider override
    # Values: None (use routing table) | "claude" | "gemini" | "openai"
    llm_provider_override = Column(String(20), nullable=True)

    # ── Dograh voice AI (migration 025) ──────────────────────────────────────
    # voice_platform: which IVR adapter handles calls — "callerdesk"|"acefone"|"dograh"
    voice_platform = Column(String(50), nullable=True, server_default="callerdesk")
    dograh_agent_id = Column(String(255), nullable=True)
    # Fernet-encrypted JSON: {"webhook_secret": "<hex>"} — same pattern as Integration.credentials_kms_blob
    dograh_webhook_secret_enc = Column(LargeBinary, nullable=True)
    sip_trunk_provider = Column(String(50), nullable=True)
    sip_trunk_number = Column(String(20), nullable=True)

    # Leads360: per-tenant pipeline stage display config (label, color, order, visible)
    pipeline_config = Column(JSON, nullable=True)

    # Adaptive dashboard: {"selected_widgets": [...], "customized_at": "ISO"}
    dashboard_config = Column(JSON, nullable=True)

    # T3.2: per-tenant Instagram AI concierge defaults -- Ratha and Jade can
    # carry different risk tolerance without a code change. New conversations
    # inherit ig_ai_mode_default; concierge_draft.py reads
    # ig_ai_confidence_threshold instead of a hardcoded constant.
    ig_ai_mode_default = Column(String(20), nullable=False, server_default="shadow")
    ig_ai_confidence_threshold = Column(Float, nullable=False, server_default="0.78")

    # WhatsApp equivalents (migration 079). Before these existed whatsapp.py
    # hardcoded ai_mode="shadow" and concierge_draft.py applied the *Instagram*
    # threshold to WhatsApp drafts.
    wa_ai_mode_default = Column(String(20), nullable=False, server_default="shadow")
    wa_ai_confidence_threshold = Column(Float, nullable=False, server_default="0.78")

    # Emergency stop (migration 080). When true the AI stops sending to
    # guests on every channel immediately, regardless of the mode settings
    # above. Drafting continues so agents keep the assist -- this halts
    # delivery, not the feature.
    # sa.text("false"), not the string "false": a plain string renders as
    # DEFAULT 'false', which SQLite stores as a non-empty string and reads
    # back as True -- i.e. the kill switch would default to ON and silently
    # disable the AI. Postgres coerces it correctly, so this only bites on
    # SQLite (the test database), which is exactly where it is hardest to
    # notice.
    ai_kill_switch = Column(Boolean, nullable=False, server_default=sa_text("false"), default=False)
    ai_kill_switch_at = Column(DateTime(timezone=True), nullable=True)
    ai_kill_switch_by = Column(String, nullable=True)
    ai_kill_switch_reason = Column(String(500), nullable=True)
    # Tenant additions on top of the built-in escalation list, never a
    # replacement for it.
    ai_escalation_keywords = Column(JSON, nullable=True)

    users = relationship("User", back_populates="tenant", lazy="dynamic")
    guests = relationship("Guest", back_populates="tenant", lazy="dynamic")
    properties = relationship("Property", back_populates="tenant", lazy="dynamic")
    integrations = relationship("Integration", back_populates="tenant", lazy="dynamic")
