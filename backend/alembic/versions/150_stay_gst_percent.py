"""New-booking flow: the GST slab a booking was priced with.

Schema (additive, idempotent: production builds tables with create_all at startup, so the step checks first). No new table,
so no new RLS policy: stays keeps its existing tenant policy.
  * stays.gst_percent   NUMERIC(5,2) NULL   the slab chosen in /dashboard/bookings/new (0, 5, 18, 40 ...). The booking total
                                            already includes that GST, so the invoice splits it at this rate; NULL = the
                                            invoice profile's rate, as before.

Pickup and return times already exist (stays.check_in_time / check_out_time, migration 110); the time-aware clash rule needs
no schema change.

Numbering: 147 and 149 are left for other open branches; this follows 148 (the head when it was written).

Revision ID: 150
Revises: 148
"""
import sqlalchemy as sa
from alembic import op

revision = "150"
down_revision = "148"
branch_labels = None
depends_on = None

TABLE = "stays"
COLUMN = "gst_percent"


def upgrade():
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}
    if COLUMN not in cols:
        op.add_column(TABLE, sa.Column(COLUMN, sa.Numeric(5, 2), nullable=True))


def downgrade():
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}
    if COLUMN in cols:
        op.drop_column(TABLE, COLUMN)
