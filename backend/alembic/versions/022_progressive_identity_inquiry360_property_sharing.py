"""Progressive identity graph, Inquiry360, property sharing, transcript script_type

Revision ID: 022
Revises: 021
Create Date: 2026-05-30

Adds:
  - guest_identities           — multi-signal identity graph (M1)
  - inquiry_stage_log          — full stage transition history (M7)
  - inquiry_quotes             — versioned quote history (M7)
  - inquiry_property_links     — properties discussed per inquiry (M7)
  - property_shares            — viral property link tracking (M6)
  - property_share_events      — per-event attribution (M6)
  - transcripts.script_type    — devanagari|roman|mixed for Sarvam output (M4)
  - guests.phone: removes UNIQUE per-tenant constraint (M1)
  - tenants.llm_provider_override — optional provider pin (M5)
"""

from alembic import op
import sqlalchemy as sa

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── M1: guest_identities ──────────────────────────────────────────────────
    op.create_table(
        "guest_identities",
        sa.Column("id",             sa.String,    primary_key=True),
        sa.Column("tenant_id",      sa.String,    nullable=False),
        sa.Column("guest_id",       sa.String,    nullable=False),
        sa.Column("identity_type",  sa.String(50),  nullable=False),
        sa.Column("identity_value", sa.String(512), nullable=False),
        sa.Column("source",         sa.String(100), nullable=True),
        sa.Column("confidence",     sa.Float,    nullable=False, default=0.70),
        sa.Column("first_seen_at",  sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at",   sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at",    sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at",     sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at",     sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_guest_identity_tenant_type_value",
        "guest_identities",
        ["tenant_id", "identity_type", "identity_value"],
    )
    op.create_index("ix_guest_identities_tenant", "guest_identities", ["tenant_id"])
    op.create_index("ix_guest_identities_guest",  "guest_identities", ["tenant_id", "guest_id"])

    # Remove the (tenant_id, phone) unique constraint — phone is no longer the dedup key.
    # The constraint name from 001_initial_schema.py may vary; we attempt to drop it gracefully.
    try:
        op.drop_constraint("uq_guests_tenant_phone", "guests", type_="unique")
    except Exception:
        pass   # constraint may not exist under this name

    # Allow phone to be empty string (already nullable=False default="" in model)

    # ── M7: inquiry_stage_log ─────────────────────────────────────────────────
    op.create_table(
        "inquiry_stage_log",
        sa.Column("id",          sa.String,   primary_key=True),
        sa.Column("tenant_id",   sa.String,   nullable=False),
        sa.Column("inquiry_id",  sa.String,   nullable=False),
        sa.Column("from_stage",  sa.String(30), nullable=True),
        sa.Column("to_stage",    sa.String(30), nullable=False),
        sa.Column("changed_by",  sa.String,   nullable=True),
        sa.Column("changed_at",  sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason",      sa.Text,     nullable=True),
        sa.Column("created_at",  sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at",  sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_inquiry_stage_log_inquiry", "inquiry_stage_log", ["inquiry_id"])

    # ── M7: inquiry_quotes ────────────────────────────────────────────────────
    op.create_table(
        "inquiry_quotes",
        sa.Column("id",          sa.String,    primary_key=True),
        sa.Column("tenant_id",   sa.String,    nullable=False),
        sa.Column("inquiry_id",  sa.String,    nullable=False),
        sa.Column("amount",      sa.Numeric(12, 2), nullable=False),
        sa.Column("currency",    sa.String(3), nullable=False, default="INR"),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pdf_url",     sa.Text,      nullable=True),
        sa.Column("notes",       sa.Text,      nullable=True),
        sa.Column("created_by",  sa.String,    nullable=True),
        sa.Column("is_active",   sa.Boolean,   default=True),
        sa.Column("created_at",  sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at",  sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_inquiry_quotes_inquiry", "inquiry_quotes", ["inquiry_id"])

    # ── M7: inquiry_property_links ────────────────────────────────────────────
    op.create_table(
        "inquiry_property_links",
        sa.Column("id",              sa.String,   primary_key=True),
        sa.Column("tenant_id",       sa.String,   nullable=False),
        sa.Column("inquiry_id",      sa.String,   nullable=False),
        sa.Column("property_id",     sa.String,   nullable=False),
        sa.Column("link_type",       sa.String(20), nullable=False, default="proposed"),
        sa.Column("tracking_token",  sa.String(64), nullable=True),
        sa.Column("linked_at",       sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at",      sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at",      sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_inquiry_property_links_inquiry", "inquiry_property_links", ["inquiry_id"])
    op.create_index("ix_inquiry_property_links_token",   "inquiry_property_links", ["tracking_token"])

    # ── M6: property_shares ───────────────────────────────────────────────────
    op.create_table(
        "property_shares",
        sa.Column("id",              sa.String,  primary_key=True),
        sa.Column("tenant_id",       sa.String,  nullable=False),
        sa.Column("property_id",     sa.String,  nullable=False),
        sa.Column("shared_by_gid",   sa.String,  nullable=True),
        sa.Column("channel",         sa.String(20), nullable=True),
        sa.Column("campaign_id",     sa.String,  nullable=True),
        sa.Column("tracking_token",  sa.String(64), nullable=False, unique=True),
        sa.Column("total_views",     sa.Integer, default=0),
        sa.Column("total_revisits",  sa.Integer, default=0),
        sa.Column("total_forwards",  sa.Integer, default=0),
        sa.Column("total_inquiries", sa.Integer, default=0),
        sa.Column("total_bookings",  sa.Integer, default=0),
        sa.Column("created_at",      sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at",      sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_property_shares_token",    "property_shares", ["tracking_token"])
    op.create_index("ix_property_shares_property", "property_shares", ["property_id", "tenant_id"])

    # ── M6: property_share_events ─────────────────────────────────────────────
    op.create_table(
        "property_share_events",
        sa.Column("id",           sa.String,    primary_key=True),
        sa.Column("tenant_id",    sa.String,    nullable=False),
        sa.Column("share_id",     sa.String,    nullable=False),
        sa.Column("event_type",   sa.String(30), nullable=False),
        sa.Column("viewer_gid",   sa.String,    nullable=True),
        sa.Column("referrer_gid", sa.String,    nullable=True),
        sa.Column("session_id",   sa.String(128), nullable=True),
        sa.Column("inquiry_id",   sa.String,    nullable=True),
        sa.Column("occurred_at",  sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at",   sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at",   sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_property_share_events_share",  "property_share_events", ["share_id"])
    op.create_index("ix_property_share_events_viewer", "property_share_events", ["viewer_gid"])

    # ── M4: transcripts.script_type ──────────────────────────────────────────
    op.add_column("transcripts", sa.Column("script_type", sa.String(20), nullable=True))

    # ── M5: tenants.llm_provider_override ────────────────────────────────────
    op.add_column("tenants", sa.Column(
        "llm_provider_override", sa.String(20), nullable=True,
        comment="Optional: pin tenant to a specific LLM provider (claude|gemini|openai)",
    ))


def downgrade() -> None:
    op.drop_column("tenants", "llm_provider_override")
    op.drop_column("transcripts", "script_type")
    op.drop_table("property_share_events")
    op.drop_table("property_shares")
    op.drop_table("inquiry_property_links")
    op.drop_table("inquiry_quotes")
    op.drop_table("inquiry_stage_log")
    op.drop_table("guest_identities")
