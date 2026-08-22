"""IVR call routing: agent pool, round robin / parallel ring, greeting audio.

The live Vobiz Answer webhook (webhooks_vobiz.py) currently dials one
hardcoded number per tenant (Integration.credentials["forward_number"]) with
no distribution across agents and no greeting before the ring. This adds:

- tenants.ivr_routing_strategy -- "single" (unchanged behaviour, the
  default so no existing tenant's calls change until they opt in) /
  "round_robin" (rotate through eligible agents one call at a time) /
  "parallel" (ring every eligible agent's number at once, first to answer
  gets the call -- native Dial-with-multiple-Number behaviour).
- tenants.ivr_greeting_audio_key -- S3 key (not URL; URLs are presigned
  fresh on read, same convention as media_storage.py) for a client-
  uploaded MP3 played before the agent leg dials.
- users.ivr_call_routing_enabled -- opt-in per user. The agent pool for
  round_robin/parallel is existing HAIP users with a phone number and this
  flag set, not a separate number list -- CLAUDE.md already frames agents
  as real system users taking calls on their personal mobile.

Revision ID: 084
Revises: 083
Create Date: 2026-08-22
"""
from alembic import op
import sqlalchemy as sa

revision = "084"
down_revision = "083"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "tenants",
        sa.Column(
            "ivr_routing_strategy", sa.String(20),
            nullable=False, server_default="single",
        ),
    )
    op.add_column(
        "tenants",
        sa.Column("ivr_greeting_audio_key", sa.String(500), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "ivr_call_routing_enabled", sa.Boolean(),
            # Plain string "false" reads back truthy on SQLite (bit us on
            # migration 080's ai_kill_switch) -- sa.text() is the fix.
            nullable=False, server_default=sa.text("false"),
        ),
    )


def downgrade():
    op.drop_column("users", "ivr_call_routing_enabled")
    op.drop_column("tenants", "ivr_greeting_audio_key")
    op.drop_column("tenants", "ivr_routing_strategy")
