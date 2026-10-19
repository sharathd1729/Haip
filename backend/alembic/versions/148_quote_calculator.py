"""Rate calculator quotes: how a quote reached the guest and who approved a lowered price.

Schema (additive, idempotent: production builds tables with create_all at startup, so every step checks first). No new table,
so no new RLS policy: inquiry_quotes keeps its existing tenant policy.
  * inquiry_quotes.shared_via   VARCHAR(20) NULL     "sent" (WhatsApp) | "copied" (the agent copied the text); NULL = saved only
  * inquiry_quotes.shared_at    TIMESTAMPTZ NULL     when it was last sent or copied
  * inquiry_quotes.approved_by  VARCHAR NULL         the owner/manager who approved a price more than the limit below suggested
  * inquiry_quotes.approved_at  TIMESTAMPTZ NULL

A quote waiting for that approval has status "pending_approval" (the column already exists, VARCHAR(20)).

Numbering: 147 is reserved by another branch; this follows 145 (the head when it was written).

Revision ID: 148
Revises: 145
"""
import sqlalchemy as sa
from alembic import op

revision = "148"
down_revision = "145"
branch_labels = None
depends_on = None

TABLE = "inquiry_quotes"
COLUMNS = (
    ("shared_via", lambda: sa.String(20)),
    ("shared_at", lambda: sa.DateTime(timezone=True)),
    ("approved_by", lambda: sa.String()),
    ("approved_at", lambda: sa.DateTime(timezone=True)),
)


def upgrade():
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}
    for name, kind in COLUMNS:
        if name not in cols:
            op.add_column(TABLE, sa.Column(name, kind(), nullable=True))


def downgrade():
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}
    for name, _ in reversed(COLUMNS):
        if name in cols:
            op.drop_column(TABLE, name)
