"""Batch fix for schema drift discovered via fresh-DB audit

Multiple columns existed on live Neon (added directly, never migrated)
but were missing from migration history entirely. Found by comparing
Base.metadata against a freshly-built Supabase schema.

Revision ID: 040
Revises: 039
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def _column_exists(table: str, col: str) -> bool:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    return col in {c["name"] for c in insp.get_columns(table)}


def _add(table: str, column: sa.Column) -> None:
    if not _column_exists(table, column.name):
        op.add_column(table, column)


def upgrade() -> None:
    _add("users", sa.Column("is_available_for_assignment", sa.Boolean(), nullable=False, server_default="true"))
    _add("users", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))

    _add("guests", sa.Column("deletion_state", sa.String(20), nullable=False, server_default="none"))
    _add("guests", sa.Column("deletion_requested_at", sa.String(), nullable=True))
    _add("guests", sa.Column("deletion_completed_at", sa.String(), nullable=True))

    _add("conversations", sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True))

    _add("consents", sa.Column("proof_ip", sa.String(64), nullable=True))
    _add("consents", sa.Column("proof_user_agent", sa.Text(), nullable=True))
    _add("consents", sa.Column("proof_source", sa.String(255), nullable=True))
    _add("consents", sa.Column("notice_version", sa.String(20), nullable=True))
    _add("consents", sa.Column("notice_text_hash", sa.String(64), nullable=True))
    _add("consents", sa.Column("consent_payload", sa.JSON(), nullable=True))
    _add("consents", sa.Column("withdrawn_at", sa.String(), nullable=True))
    _add("consents", sa.Column("withdrawal_reason", sa.String(100), nullable=True))


def downgrade() -> None:
    for table, col in [
        ("users", "is_available_for_assignment"),
        ("users", "last_seen_at"),
        ("guests", "deletion_state"),
        ("guests", "deletion_requested_at"),
        ("guests", "deletion_completed_at"),
        ("conversations", "snoozed_until"),
        ("consents", "proof_ip"),
        ("consents", "proof_user_agent"),
        ("consents", "proof_source"),
        ("consents", "notice_version"),
        ("consents", "notice_text_hash"),
        ("consents", "consent_payload"),
        ("consents", "withdrawn_at"),
        ("consents", "withdrawal_reason"),
    ]:
        if _column_exists(table, col):
            op.drop_column(table, col)
