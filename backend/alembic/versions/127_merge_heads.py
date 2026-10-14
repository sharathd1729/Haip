"""Merge the Ratha/knowledge chain (122-125) with the organic-call source (126).

feat/ratha-business-data (122-125) and phase0-reliability (126) both hang off 121, so merging them leaves two heads; this revision joins
them. It changes no schema.

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
