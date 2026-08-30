"""embeddings/transcripts vector columns: 1024 -> 2048 dims.

nvidia/nv-embedqa-e5-v5 (the 1024-dim model migration 078 sized this column
for) reached NVIDIA NIM end-of-life 2026-08-25 -- confirmed live via HTTP
410 Gone, breaking concierge KB search (kb_search_embed_failed) in prod.

Every other embedqa-family model on NIM's catalog (nvidia/embed-qa-4,
nvidia/llama-3.2-nv-embedqa-1b-v1, nvidia/nv-embedqa-mistral-7b-v2,
snowflake/arctic-embed-l) 404s as "not found for account" -- not entitled
on this NVIDIA account, confirmed live, not a guess. The only embedding
model actually callable is nvidia/nemotron-3-embed-1b, which emits 2048
dims (confirmed live) with no dimensionality-reduction option (a
dimensions=1024 request 400s: "dimensions must be one of 2048").

pgvector 0.8.2 (confirmed live) hard-caps both ivfflat and hnsw indexes at
2000 dimensions, so 2048 cannot be ANN-indexed. Verified this is fine at
current scale: `embeddings` has 58 rows, `transcripts.embedding` has zero
populated rows (unused in prod). A plain sequential scan on the `<=>`
distance operator (knowledge_service.search() already uses this operator,
no index hint) is effectively free at this size. If this table grows large
enough for that to matter, revisit -- either get one of the 404ing models
entitled on this account, or an alternative provider.

The old 1024-dim vectors are semantically meaningless once cast to
2048 dims (not a valid representation, not a truncation) -- nulled out
here, not preserved. All 58 knowledge_entries are reset to
embedding_status='pending' so the existing knowledge.embed_pending Celery
task (embed_knowledge.py) regenerates them for real against the new model
-- this migration does not itself call the embeddings API.

Revision ID: 094
Revises: 093
Create Date: 2026-08-30
"""
from alembic import op

revision = "094"
down_revision = "093"
branch_labels = None
depends_on = None


def upgrade():
    # ── embeddings: 1024 → 2048, drop the now-oversized ivfflat index ────────
    op.execute("DROP INDEX IF EXISTS ix_embeddings_vec")
    op.execute("ALTER TABLE embeddings ALTER COLUMN embedding TYPE vector(2048) USING NULL")
    # No index recreated -- pgvector caps ivfflat/hnsw at 2000 dims (verified
    # live). Fine at 58 rows; see module docstring if this table grows.

    # ── transcripts.embedding: kept in sync, zero rows affected today ────────
    op.execute("ALTER TABLE transcripts ALTER COLUMN embedding TYPE vector(2048) USING NULL")

    # Force every KB entry to re-embed against the new model.
    op.execute("UPDATE knowledge_entries SET embedding_status = 'pending', embedded_at = NULL")


def downgrade():
    op.execute("ALTER TABLE transcripts ALTER COLUMN embedding TYPE vector(1024) USING NULL")

    op.execute("ALTER TABLE embeddings ALTER COLUMN embedding TYPE vector(1024) USING NULL")
    op.execute(
        "CREATE INDEX ix_embeddings_vec ON embeddings "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )
    op.execute("UPDATE knowledge_entries SET embedding_status = 'pending', embedded_at = NULL")
