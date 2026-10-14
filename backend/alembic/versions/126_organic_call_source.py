"""Add 'organic_call' to the inquiry source enum.

An inbound call that arrived with no ad or campaign behind it. Existing rows are NOT re-labelled: a lead keeps the source it
was recorded with. PostgreSQL only; SQLite stores the enum as text and needs nothing.

Revision ID: 126
Revises: 121

Numbering: 122-125 belong to the lead-identification, knowledge and business-data branches (feat/mai3-reliability,
feat/ratha-business-data). This revision is 126 so it sorts after them; until those branches merge it hangs off 121, and the
merge needs alembic/proposed/127_merge_heads.py (two heads: 125 and 126).
"""
from alembic import op

revision = "126"
down_revision = "121"
branch_labels = None
depends_on = None

# ALTER TYPE ... ADD VALUE cannot run inside a transaction block.
transaction_per_migration = False


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TYPE inquirysource ADD VALUE IF NOT EXISTS 'organic_call'")


def downgrade() -> None:
    # PostgreSQL cannot drop an enum value; leaving it is harmless (nothing reads it once the code is rolled back).
    pass
