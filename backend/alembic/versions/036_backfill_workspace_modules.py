"""IAM Phase 0: backfill workspace_modules for existing tenants

Every tenant created before the module registry existed (migration 031) has
zero workspace_modules rows and today relies on a permissive code fallback
in deps.py::get_workspace_context — this backfill gives them real rows
matching that same default set, so the fallback can be safely flipped to
fail-closed in the same deploy (see deps.py change alongside this migration).

Revision ID: 036
Revises: 035
Create Date: 2026-07-19
"""
from alembic import op

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None

_DEFAULT_MODULE_CODES = (
    "whatsapp", "instagram", "calls", "leads360", "channel_manager",
    "analytics", "ask_haip", "ai_concierge", "campaigns", "flow_builder",
)


def upgrade():
    codes_sql = ", ".join(f"'{c}'" for c in _DEFAULT_MODULE_CODES)
    op.execute(f"""
        INSERT INTO workspace_modules (id, workspace_id, module_id, enabled, config)
        SELECT gen_random_uuid()::text, t.id, m.id, true, '{{}}'::jsonb
        FROM tenants t
        CROSS JOIN modules m
        WHERE m.code IN ({codes_sql})
        ON CONFLICT (workspace_id, module_id) DO NOTHING
    """)


def downgrade():
    # Not reversible in a targeted way (can't distinguish backfilled rows
    # from ones a workspace activated itself afterward) — no-op.
    pass
