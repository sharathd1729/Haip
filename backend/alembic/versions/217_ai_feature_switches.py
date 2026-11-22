"""Settings > AI switches (docs/ai/AI_SWITCHES_SPEC.md, step 1): tenants.ai_features (JSON, missing key = the default in
services/ai_features.py) and tenants.ig_comment_ai_mode_default (Instagram comments' own reply mode, default off). A
workspace whose call AI was paused (brand_config.calls_ai_paused) keeps it paused through the two new switches, and the old
key is removed so there is one place for it. No new table. Idempotent (production runs create_all at startup).

Revision ID: 217
Revises: 216
"""

from alembic import op

revision = "217"
down_revision = "216"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS ai_features JSON")
    op.execute(
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS ig_comment_ai_mode_default VARCHAR(20) NOT NULL DEFAULT 'off'"
    )
    op.execute("""
        UPDATE tenants
           SET ai_features = (COALESCE(ai_features::jsonb, '{}'::jsonb)
                              || '{"call_transcription": false, "call_analysis": false}'::jsonb)::json,
               brand_config = (brand_config::jsonb - 'calls_ai_paused')::json
         WHERE brand_config IS NOT NULL AND (brand_config::jsonb ->> 'calls_ai_paused') = 'true'
    """)


def downgrade():
    op.execute("""
        UPDATE tenants
           SET brand_config = (COALESCE(brand_config::jsonb, '{}'::jsonb) || '{"calls_ai_paused": true}'::jsonb)::json
         WHERE ai_features IS NOT NULL AND (ai_features::jsonb ->> 'call_transcription') = 'false'
    """)
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS ig_comment_ai_mode_default")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS ai_features")
