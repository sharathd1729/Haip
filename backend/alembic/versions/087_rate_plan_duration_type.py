"""Caravan rate-plan duration bucketing.

_resolve_rate() in calculator_service.py picked between a caravan
property's active RatePlan rows with a plain `.first()` -- no ordering,
no match against which product (day / overnight / multi-day) the guest
actually asked for. Confirmed live on Ratha's two caravans: 3 active
RatePlan rows each ("One-Day Caravan Experience" ~25000, "Overnight
Caravan Retreat" ~42000, "Multi-Day Curated Journeys" ~0), any one of
which could silently win for any quote.

This column lets calculator_service filter by the guest's actual
requested duration instead. Nullable and only consulted when
property.type == "caravan" (see calculator_service.py), so every
existing villa RatePlan is unaffected and stays NULL.

Backfill is tenant-agnostic (joins through properties.type = 'caravan',
not a hardcoded tenant id) so it also tags any other caravan tenant's
plans that happen to follow the same naming convention -- rows that
don't match any pattern are left NULL, same as if this migration had
never touched them.

Revision ID: 087
Revises: 086
Create Date: 2026-08-24
"""
from alembic import op
import sqlalchemy as sa

revision = "087"
down_revision = "086"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("rate_plans", sa.Column("duration_type", sa.String(20), nullable=True))

    op.execute("""
        UPDATE rate_plans rp
        SET duration_type = 'same_day'
        FROM properties p
        WHERE p.id = rp.property_id
          AND p.type = 'caravan'
          AND (rp.name ILIKE '%one-day%' OR rp.name ILIKE '%one day%'
               OR rp.name ILIKE '%full day%' OR rp.name ILIKE '%day experience%')
    """)
    op.execute("""
        UPDATE rate_plans rp
        SET duration_type = 'overnight'
        FROM properties p
        WHERE p.id = rp.property_id
          AND p.type = 'caravan'
          AND rp.name ILIKE '%overnight%'
    """)
    op.execute("""
        UPDATE rate_plans rp
        SET duration_type = 'multiday'
        FROM properties p
        WHERE p.id = rp.property_id
          AND p.type = 'caravan'
          AND (rp.name ILIKE '%multi-day%' OR rp.name ILIKE '%multiday%' OR rp.name ILIKE '%multi day%')
    """)


def downgrade():
    op.drop_column("rate_plans", "duration_type")
