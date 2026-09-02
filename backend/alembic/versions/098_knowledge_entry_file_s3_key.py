"""Knowledge base ingestion: website crawling + document upload.

Adds `knowledge_entries.file_s3_key` -- the original uploaded document
(PDF/DOCX/TXT) is stored in R2 (media_storage.py's existing S3-compatible
client, same pattern as WhatsApp media/IVR audio/avatars -- NOT Supabase
storage) so it stays retrievable for reference/audit even though the row
itself only carries the extracted, chunked text. NULL for every other
source (manual entries, website-scraped chunks -- those have source_url
instead, no file to store).

Revision ID: 098
Revises: 097
Create Date: 2026-09-03
"""
from alembic import op
import sqlalchemy as sa

revision = "098"
down_revision = "097"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    conn = op.get_bind()
    return column in [c["name"] for c in sa.inspect(conn).get_columns(table)]


def upgrade() -> None:
    if not _has_column("knowledge_entries", "file_s3_key"):
        op.add_column("knowledge_entries", sa.Column("file_s3_key", sa.String(500), nullable=True))


def downgrade() -> None:
    if _has_column("knowledge_entries", "file_s3_key"):
        op.drop_column("knowledge_entries", "file_s3_key")
