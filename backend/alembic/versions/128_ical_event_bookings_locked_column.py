"""Make sure ical_event_bookings has its ``locked`` column.

Migration 121 creates the table with ``CREATE TABLE IF NOT EXISTS``. On production the table already existed (created earlier by the
startup ``create_all`` from a model without ``locked``), so 121 skipped it and the column never appeared: every query that read the
table failed with "column ical_event_bookings.locked does not exist", which broke every booking page (503). This adds the column when it
is missing and does nothing when it is there. Additive only; no downgrade (the model needs the column).

Revision ID: 128
Revises: 127
"""
from alembic import op

revision = "128"
down_revision = "127"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ical_event_bookings ADD COLUMN IF NOT EXISTS locked BOOLEAN NOT NULL DEFAULT false")


def downgrade() -> None:
    pass        # the column belongs to the model; dropping it would break the app
