"""Marketing Studio phase 5 (plan 24 Oct 2026): Conversions API lead events (LeadSubmitted, QualifiedLead).

marketing_capi_events (tenant table, RLS unchanged) gets `inquiry_id` and `stay_id` becomes nullable (a lead event has
no stay); a unique index keeps one event of each name per enquiry. Idempotent. On SQLite the NOT NULL is left alone
(tests build the table from the models). Downgrade drops the column and index; it does not restore NOT NULL (lead rows
without a stay would block it).

Revision ID: 177
Revises: 176
Create Date: 2026-10-24
"""
from alembic import op

revision = "177"
down_revision = "176"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '10s'")
        op.execute("ALTER TABLE marketing_capi_events ADD COLUMN IF NOT EXISTS inquiry_id VARCHAR")
        op.execute("ALTER TABLE marketing_capi_events ALTER COLUMN stay_id DROP NOT NULL")
    elif "inquiry_id" not in {row[1] for row in bind.exec_driver_sql("PRAGMA table_info(marketing_capi_events)")}:
        op.execute("ALTER TABLE marketing_capi_events ADD COLUMN inquiry_id VARCHAR")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_marketing_capi_events_inquiry "
               "ON marketing_capi_events (tenant_id, inquiry_id, event_name)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_marketing_capi_events_inquiry")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE marketing_capi_events DROP COLUMN IF EXISTS inquiry_id")
    else:
        op.drop_column("marketing_capi_events", "inquiry_id")
