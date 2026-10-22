"""CRM reporting (22 Oct 2026): lead type, and a person's "Valid enquiry?" review on each enquiry.

Adds columns to an existing tenant-scoped table (its RLS policy is unchanged; no new table):
  * inquiries.lead_type VARCHAR(20) NOT NULL DEFAULT 'guest'   -- guest | b2b | partner (schemas/lead_review.py)
  * inquiries.validation_status VARCHAR(10)                     -- valid | invalid, NULL = nobody has reviewed it
  * inquiries.validation_dates_confirmed / validation_budget_fits / validation_clear_intent BOOLEAN -- the three checks
  * inquiries.validation_note VARCHAR(300)
  * inquiries.validated_by VARCHAR (users.id, SET NULL on delete) / validated_at TIMESTAMPTZ
  * index ix_inquiries_tenant_id_lead_type
ADD COLUMN / CREATE INDEX IF NOT EXISTS, so it is idempotent and repairs a table created by create_all (prod runs create_all
at startup). Existing rows become 'guest' through the column default. Downgrade drops only these.

Revision 169 on 167: 168 is reserved by a parallel branch; a merge migration joins them when both land.

Revision ID: 169
Revises: 167
"""
from alembic import op

revision = "169"
down_revision = "167"
branch_labels = None
depends_on = None

COLUMNS = (
    ("lead_type", "VARCHAR(20) NOT NULL DEFAULT 'guest'"),
    ("validation_status", "VARCHAR(10)"),
    ("validation_dates_confirmed", "BOOLEAN"),
    ("validation_budget_fits", "BOOLEAN"),
    ("validation_clear_intent", "BOOLEAN"),
    ("validation_note", "VARCHAR(300)"),
    ("validated_by", "VARCHAR"),
    ("validated_at", "TIMESTAMP WITH TIME ZONE"),
)
INDEX = "ix_inquiries_tenant_id_lead_type"


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '10s'")
        for name, kind in COLUMNS:
            if name == "validated_by":
                kind = "VARCHAR REFERENCES users(id) ON DELETE SET NULL"
            op.execute(f"ALTER TABLE inquiries ADD COLUMN IF NOT EXISTS {name} {kind}")
        op.execute(f"CREATE INDEX IF NOT EXISTS {INDEX} ON inquiries (tenant_id, lead_type)")
        return
    existing = {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(inquiries)")}
    for name, kind in COLUMNS:
        if name not in existing:
            op.execute(f"ALTER TABLE inquiries ADD COLUMN {name} {kind}")
    op.execute(f"CREATE INDEX IF NOT EXISTS {INDEX} ON inquiries (tenant_id, lead_type)")


def downgrade():
    bind = op.get_bind()
    op.execute(f"DROP INDEX IF EXISTS {INDEX}")
    for name, _ in reversed(COLUMNS):
        if bind.dialect.name == "postgresql":
            op.execute(f"ALTER TABLE inquiries DROP COLUMN IF EXISTS {name}")
        else:
            op.drop_column("inquiries", name)
