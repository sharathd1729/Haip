"""Stays.check_in/check_out String -> DATE (HAIP_Dashboard_Metrics_Plan.md
Phase 2, step 2.2, F5) -- renumbered from the plan's assumed "069" (see
069's docstring for why; this is the migration that assumption was
building toward)

Occupancy, ADR and RevPAR are not computable in SQL without casting every
row, and Ratha's stays were entered manually so format consistency
couldn't be assumed going in. Pre-flight check against production
(2026-08-08): 12 stays, 0 unparseable dates -- the exact risk this
migration guards against didn't materialize for Ratha, but the migration
runs across every tenant, not just Ratha, so the tolerant-parse +
quarantine path is real protection, not defensive theater.

Two passes before the type change:
  1. Normalise recognised alternate formats (DD/MM/YYYY, DD-MM-YYYY) to
     ISO in place.
  2. Anything still not ISO after that gets copied into
     stays_date_quarantine (full snapshot, not just an FK) and removed
     from the live table -- "quarantine", not "drop". check_in/check_out
     stay NOT NULL on stays; a row with an unrecoverable date can't sit
     there with a null date pretending to be valid, and can't block the
     ALTER for every other row either.

Revision ID: 071
Revises: 070
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

revision = "071"
down_revision = "070"
branch_labels = None
depends_on = None

_ISO = r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
_DMY_SLASH = r'^[0-9]{2}/[0-9]{2}/[0-9]{4}$'
_DMY_DASH = r'^[0-9]{2}-[0-9]{2}-[0-9]{4}$'


def upgrade():
    bind = op.get_bind()

    op.create_table(
        "stays_date_quarantine",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("stay_id", sa.String(), nullable=False),
        sa.Column("guest_id", sa.String(), nullable=True),
        sa.Column("property_id", sa.String(), nullable=True),
        sa.Column("original_check_in", sa.String(), nullable=True),
        sa.Column("original_check_out", sa.String(), nullable=True),
        sa.Column("status", sa.String(30), nullable=True),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("quarantined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_stays_date_quarantine_tenant", "stays_date_quarantine", ["tenant_id"])

    # ── Pass 1: normalise recognised alternate formats to ISO in place ──────
    for pattern, pg_format in ((_DMY_SLASH, "DD/MM/YYYY"), (_DMY_DASH, "DD-MM-YYYY")):
        for col in ("check_in", "check_out"):
            bind.execute(sa.text(
                f"""
                UPDATE stays
                SET {col} = to_char(to_date({col}, :fmt), 'YYYY-MM-DD')
                WHERE {col} ~ :pattern
                """
            ), {"fmt": pg_format, "pattern": pattern})

    # ── Pass 2: quarantine anything still not ISO on either column ──────────
    bind.execute(sa.text(
        f"""
        INSERT INTO stays_date_quarantine
            (id, tenant_id, stay_id, guest_id, property_id,
             original_check_in, original_check_out, status, total_amount, reason)
        SELECT
            gen_random_uuid()::text, tenant_id, id, guest_id, property_id,
            check_in, check_out, status, total_amount,
            CASE
                WHEN check_in !~ :iso AND check_out !~ :iso THEN 'both dates unparseable'
                WHEN check_in !~ :iso THEN 'check_in unparseable'
                ELSE 'check_out unparseable'
            END
        FROM stays
        WHERE check_in !~ :iso OR check_out !~ :iso
        """
    ), {"iso": _ISO})

    bind.execute(sa.text(
        "DELETE FROM stays WHERE id IN (SELECT stay_id FROM stays_date_quarantine)"
    ))

    # ── Type change -- every remaining row is now guaranteed valid ISO ──────
    op.alter_column("stays", "check_in", type_=sa.Date(), postgresql_using="check_in::date")
    op.alter_column("stays", "check_out", type_=sa.Date(), postgresql_using="check_out::date")


def downgrade():
    op.alter_column("stays", "check_in", type_=sa.String(), postgresql_using="check_in::text")
    op.alter_column("stays", "check_out", type_=sa.String(), postgresql_using="check_out::text")
    # Quarantined rows are NOT restored to `stays` on downgrade -- their
    # dates were never valid in the first place, so there's nothing safe to
    # restore them as. The quarantine table itself is left in place (not
    # dropped) so the records aren't lost.
