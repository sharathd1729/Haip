"""WhatsApp module T0.3: add 'submission_failed' to TemplateStatus enum

wa_templates.status was created via create_all() (never a proper
migration, per messaging.py's own header comment) using SQLAlchemy's
default Postgres enum naming (lowercase class name: "templatestatus").
Adding a new member here so submit_template() can distinguish a genuine
Meta API failure from "awaiting review" (previously both landed on
PENDING, indistinguishable in the UI).

Revision ID: 046
Revises: 045
Create Date: 2026-07-15
"""
from alembic import op
import sqlalchemy as sa

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade():
    # The enum type only exists on databases whose wa_templates came from
    # create_all() (production). A database built purely from migrations gets
    # wa_templates from 017, which declares status as plain TEXT — there is no
    # type to ALTER, and TEXT already accepts the new value, so the statement
    # is not merely unsafe there but unnecessary.
    #
    # Without this guard `alembic upgrade head` dies here on any fresh database
    # ("type templatestatus does not exist"), and because Alembic wraps the run
    # in a single transaction the whole chain rolls back — leaving an empty DB
    # and no alembic_version row. That blocked CI and any new environment.
    type_exists = op.get_bind().execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = 'templatestatus'")
    ).first() is not None

    if type_exists:
        op.execute("ALTER TYPE templatestatus ADD VALUE IF NOT EXISTS 'submission_failed'")


def downgrade():
    # Postgres has no DROP VALUE for enums -- not reversible without
    # recreating the type. No-op, matching the pattern used elsewhere in
    # this codebase for non-reversible additive changes.
    pass
