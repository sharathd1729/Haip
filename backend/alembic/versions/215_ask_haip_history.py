"""Ask HAIP chat history (workspace redesign Phase 3): ask_haip_freeform_queries keeps which chat a question belongs to
(session_id) and the answer text (narrative), so the owner's chats survive a new device and are listed by day like Ask
Yaad's. The table already has tenant_id and its RLS policy. Idempotent (production runs create_all at startup).

Revision ID: 215
Revises: 214
"""
from alembic import op

revision = "215"
down_revision = "214"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE ask_haip_freeform_queries ADD COLUMN IF NOT EXISTS session_id VARCHAR(40)")
    op.execute("ALTER TABLE ask_haip_freeform_queries ADD COLUMN IF NOT EXISTS narrative TEXT")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ask_haip_freeform_queries_tenant_session "
               "ON ask_haip_freeform_queries (tenant_id, session_id)")


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_ask_haip_freeform_queries_tenant_session")
    op.execute("ALTER TABLE ask_haip_freeform_queries DROP COLUMN IF EXISTS narrative")
    op.execute("ALTER TABLE ask_haip_freeform_queries DROP COLUMN IF EXISTS session_id")
