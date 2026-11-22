"""An internal workspace, "haip-internal", that holds the usage_events rows of AI work HAIP does for itself where no client
workspace exists (ai_features.PLATFORM_TASKS: the property-assessment write-up for HAIP's own prospects). usage_events needs
a tenant (NOT NULL, FK, RLS), so these rows go here, module "haip_internal", and their cost is visible like any other.

Inactive, no users, every AI switch off. No new table. Idempotent (production runs create_all at startup).

Revision ID: 218
Revises: 217
"""

from alembic import op

revision = "218"
down_revision = "217"
branch_labels = None
depends_on = None

INTERNAL = "haip-internal"
_OFF = (
    '{"call_analysis": false, "call_transcription": false, "lead_summaries": false, '
    '"personal_whatsapp_summaries": false, "lead_autopilot": false, "briefings": false}'
)


def upgrade():
    op.execute(f"""
        INSERT INTO tenants (id, name, slug, plan, is_active, data_region, timezone, business_hours, brand_config,
                             ai_features, wa_ai_mode_default, ig_ai_mode_default, ig_comment_ai_mode_default,
                             created_at, updated_at)
        SELECT '{INTERNAL}', 'HAIP internal (platform AI use)', '{INTERNAL}', 'internal', false, 'ap-south-1',
               'Asia/Kolkata', '{{}}', '{{}}', '{_OFF}', 'off', 'off', 'off', now(), now()
         WHERE NOT EXISTS (SELECT 1 FROM tenants WHERE id = '{INTERNAL}')
    """)


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"SELECT set_config('app.tenant_id', '{INTERNAL}', true)")  # usage_events has FORCE RLS
    op.execute(f"DELETE FROM usage_events WHERE tenant_id = '{INTERNAL}'")
    op.execute(f"DELETE FROM tenants WHERE id = '{INTERNAL}'")
