"""Issued-quote snapshot on inquiry_quotes.

inquiry_quotes has existed for a long time but nothing ever wrote it: quotes were computed on the fly and forgotten, so nobody could
say what a guest had been quoted once rates changed. These columns let an issued quote keep its own copy of the lines, totals, inputs
and the exact business-record versions it was built from. Additive and nullable: existing rows and the one reader are untouched.

Revision ID: 125
Revises: 124
"""
from alembic import op

revision = "125"
down_revision = "124"
branch_labels = None
depends_on = None

COLUMNS = (
    ("package_key", "VARCHAR(60)"), ("check_in", "DATE"), ("check_out", "DATE"), ("guests", "INTEGER"),
    ("snapshot", "JSON"), ("record_refs", "JSON"), ("params_hash", "VARCHAR(64)"), ("status", "VARCHAR(20)"),
)


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '10s'")
    for name, kind in COLUMNS:
        op.execute(f"ALTER TABLE inquiry_quotes ADD COLUMN IF NOT EXISTS {name} {kind}")
    op.execute("CREATE INDEX IF NOT EXISTS ix_inquiry_quotes_params ON inquiry_quotes (tenant_id, inquiry_id, params_hash)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_inquiry_quotes_params")
    for name, _ in reversed(COLUMNS):
        op.execute(f"ALTER TABLE inquiry_quotes DROP COLUMN IF EXISTS {name}")
