"""AI-generated alternate phrasings for knowledge base entries.

One stored question only matches so much. "Do you allow pets?" reliably
catches "are animals allowed" and "pet friendly?", but misses "is it ok if
we get our labrador" -- verified against the live embedding model. Asking
the owner to hand-write every variation is the manual work this feature
exists to avoid, so the phrasings are generated.

Each phrasing is embedded as its own vector pointing at the same answer,
which is why retrieval must now deduplicate by entry (knowledge_service.
search keeps the best-scoring vector per entry).

Revision ID: 083
Revises: 082
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "083"
down_revision = "082"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "knowledge_entries",
        sa.Column("alt_phrasings", postgresql.JSONB(), nullable=True, server_default="[]"),
    )
    op.add_column(
        "knowledge_entries",
        sa.Column("alt_phrasings_generated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The vectors table now holds several rows per entry (the answer itself
    # plus one per phrasing), so lookups by entry need to be cheap.
    op.create_index("ix_embeddings_ref", "embeddings", ["tenant_id", "namespace", "ref_id"])


def downgrade():
    op.drop_index("ix_embeddings_ref", table_name="embeddings")
    op.drop_column("knowledge_entries", "alt_phrasings_generated_at")
    op.drop_column("knowledge_entries", "alt_phrasings")
