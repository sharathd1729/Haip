"""Convert inquiries.stage and inquiries.source from VARCHAR to native enums

Revision ID: 022a
Revises: 022
Create Date: 2026-07-11

Migration 001 created inquiries.stage and inquiries.source as plain
VARCHAR columns, but the SQLAlchemy models (app/models/inquiry.py) have
always declared them as sa.Enum(InquiryStage)/sa.Enum(InquirySource),
i.e. native Postgres enum types. At some point the live database was
converted to match — but that conversion was never captured as a
migration, so it only exists as schema drift on the original database.
Migration 023 (ALTER TYPE ... ADD VALUE) assumes these enum types
already exist, and fails with "type does not exist" on any database
built strictly from the migration history (e.g. a fresh Supabase DB).

This migration creates both enum types with their original (pre-023)
member sets and converts the existing VARCHAR columns to use them.
"""
from alembic import op
import sqlalchemy as sa

revision = "022a"
down_revision = "022"
branch_labels = None
depends_on = None

# Original member sets, i.e. everything migration 023 does NOT add.
_STAGE_VALUES = ["new", "responding", "quoted", "site_visit", "booked", "lost", "ghosted"]
_SOURCE_VALUES = [
    "website", "google", "meta_ig", "meta_fb", "click_to_wa", "wa_direct",
    "email", "phone", "walk_in", "referral", "travel_agent",
    "ota_airbnb", "ota_booking", "ota_vrbo",
]


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return  # enums are a Postgres-only concept here; skip on SQLite tests

    stage_enum = sa.Enum(*_STAGE_VALUES, name="inquirystage")
    source_enum = sa.Enum(*_SOURCE_VALUES, name="inquirysource")
    stage_enum.create(conn, checkfirst=True)
    source_enum.create(conn, checkfirst=True)

    op.execute(
        "ALTER TABLE inquiries ALTER COLUMN stage TYPE inquirystage "
        "USING stage::inquirystage"
    )
    op.execute(
        "ALTER TABLE inquiries ALTER COLUMN source TYPE inquirysource "
        "USING source::inquirysource"
    )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    op.execute("ALTER TABLE inquiries ALTER COLUMN stage TYPE VARCHAR(30) USING stage::text")
    op.execute("ALTER TABLE inquiries ALTER COLUMN source TYPE VARCHAR(50) USING source::text")
    op.execute("DROP TYPE IF EXISTS inquirystage")
    op.execute("DROP TYPE IF EXISTS inquirysource")
