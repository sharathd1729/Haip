"""Merge the Ratha/knowledge chain (…125) with the organic-call source (126).

NOT applied: it lives in alembic/proposed. When feat/ratha-business-data (122-125) and phase0-reliability (126) are merged there
are two heads, so move this file to alembic/versions/ in the merge commit. It changes no schema.

Revision ID: 127
Revises: 125, 126
"""
revision = "127"
down_revision = ("125", "126")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
