"""Tenant knowledge base for the AI concierge.

Creates `knowledge_entries` (the human-managed source of truth for FAQs,
amenities, add-ons, routes, locations and policies) and fixes two latent
problems on the pre-existing `embeddings` table:

  1. `embeddings` has carried tenant content since migration 001 with NO row
     level security policy -- every other tenant-scoped table in this schema
     has one. It was empty in practice (nothing ever wrote to it), so this
     was never exploitable, but it becomes so the moment the concierge starts
     writing KB vectors. Added here rather than in a separate migration
     because this migration is what first puts data in the table.

  2. The vector column is vector(1536) (OpenAI ada-002 dimensionality) but
     HAIP routes through NVIDIA NIM, whose retrieval model
     nvidia/nv-embedqa-e5-v5 emits 1024 dims. Safe to alter in place
     precisely because the table is empty -- verified before writing this.

Revision ID: 078
Revises: 077
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa

revision = "078"
down_revision = "077"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "knowledge_entries",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("category", sa.String(30), nullable=False, server_default="faq"),
        sa.Column("question", sa.String(500), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("property_id", sa.String(), sa.ForeignKey("properties.id"), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("source_url", sa.String(2000), nullable=True),
        sa.Column("source_ref", sa.String(255), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("review_status", sa.String(20), nullable=False, server_default="approved"),
        sa.Column("embedding_status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("embedding_error", sa.Text(), nullable=True),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_knowledge_entries_category", "knowledge_entries", ["category"])
    op.create_index("ix_knowledge_entries_property_id", "knowledge_entries", ["property_id"])
    op.create_index("ix_knowledge_entries_source", "knowledge_entries", ["source"])
    op.create_index("ix_knowledge_entries_is_active", "knowledge_entries", ["is_active"])
    op.create_index("ix_knowledge_entries_review_status", "knowledge_entries", ["review_status"])
    op.create_index("ix_knowledge_entries_embedding_status", "knowledge_entries", ["embedding_status"])
    op.create_index(
        "ix_knowledge_entries_tenant_retrievable",
        "knowledge_entries",
        ["tenant_id", "is_active", "review_status", "embedding_status"],
    )

    op.execute("ALTER TABLE knowledge_entries ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE knowledge_entries FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY knowledge_entries_tenant_iso ON knowledge_entries
        USING (tenant_id = current_setting('app.tenant_id', true)::text)
    """)

    # ── embeddings: retrofit RLS (see module docstring) ──────────────────────
    op.execute("ALTER TABLE embeddings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE embeddings FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY embeddings_tenant_iso ON embeddings
        USING (tenant_id = current_setting('app.tenant_id', true)::text)
    """)

    # ── embeddings: 1536 → 1024 to match nvidia/nv-embedqa-e5-v5 ─────────────
    # The ivfflat index is bound to the column type, so it must be dropped and
    # rebuilt around the ALTER.
    op.execute("DROP INDEX IF EXISTS ix_embeddings_vec")
    op.execute("ALTER TABLE embeddings ALTER COLUMN embedding TYPE vector(1024)")
    op.execute(
        "CREATE INDEX ix_embeddings_vec ON embeddings "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_embeddings_vec")
    op.execute("ALTER TABLE embeddings ALTER COLUMN embedding TYPE vector(1536)")
    op.execute(
        "CREATE INDEX ix_embeddings_vec ON embeddings "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
    op.execute("DROP POLICY IF EXISTS embeddings_tenant_iso ON embeddings")
    op.execute("ALTER TABLE embeddings NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE embeddings DISABLE ROW LEVEL SECURITY")

    op.drop_table("knowledge_entries")
