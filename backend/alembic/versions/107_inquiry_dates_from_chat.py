"""Let a later chat message correct trip dates it extracted earlier.

Real case (Ratha, Sep 2026): a lead first mentioned dates that got extracted
(or misextracted) into Inquiry.check_in/check_out, then later corrected
themselves ("For 3,4th Oct") -- the correction was silently ignored, since
generate_ai_summary.py's _apply_extracted_fields() only ever wrote check_in/
check_out when the column was still empty (the same write-once rule that is
correct for a formal quote, wrong for a date that's still being negotiated).

This column marks whether the current check_in/check_out came from that chat
extraction (True) versus a Dograh voice-call event (False/null, see
dograh_call_processor.py) -- so a later chat message can update its own
earlier guess, without a chat-text guess ever overwriting the more
authoritative voice-call-extracted date.

Revision ID: 107
Revises: 106
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa

revision = "107"
down_revision = "106"
branch_labels = None
depends_on = None


def _column_exists(table: str, col: str) -> bool:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    return col in {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    if not _column_exists("inquiries", "dates_from_chat"):
        op.add_column("inquiries", sa.Column("dates_from_chat", sa.Boolean(), nullable=True))


def downgrade() -> None:
    if _column_exists("inquiries", "dates_from_chat"):
        op.drop_column("inquiries", "dates_from_chat")
