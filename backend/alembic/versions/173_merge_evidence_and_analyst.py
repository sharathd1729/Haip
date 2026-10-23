"""Merge lead evidence + won/lost reasons (171) with the AI analyst and its learning loop (172).

feat/lead-evidence-outcomes (171) and feat/ai-analyst-learning-loop (172) both hang off 170, so landing both leaves two heads;
this revision joins them. It changes no schema.

Revision ID: 173
Revises: 171, 172
"""
revision = "173"
down_revision = ("171", "172")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
