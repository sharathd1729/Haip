"""call layer2 intent outcome fields

Revision ID: 015
Revises: 014
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None

_LAYER2_COLUMNS = [
    ("occasion", sa.String(50)),
    ("budget_signal", sa.String(100)),
    ("decision_stage", sa.String(50)),
    ("competitor_mentioned", sa.String(255)),
    ("conversion_probability", sa.Integer()),
    ("lost_reason", sa.String(100)),
]


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {c["name"] for c in inspector.get_columns("calls")}

    for col_name, col_type in _LAYER2_COLUMNS:
        if col_name not in existing_cols:
            op.add_column("calls", sa.Column(col_name, col_type, nullable=True))


def downgrade():
    for col_name, _ in reversed(_LAYER2_COLUMNS):
        op.drop_column("calls", col_name)
