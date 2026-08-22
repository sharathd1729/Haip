"""Three more IVR routing strategies: fixed order, longest idle, sticky agent.

Matches the strategy names in Vobiz's own console call-distribution picker
(Simultaneous ringing / Round Robin / Fixed order / Longest idle / Sticky
agent) -- built on our own Answer URL webhook rather than Vobiz's native
Team routing, since Vobiz's docs describe recording/webhooks as the
customer's own responsibility and don't confirm whether their console-level
Team routing still invokes the Answer URL. Using ours keeps every call
guaranteed to hit call_ingest (record -> transcribe -> analyze).

longest_idle needs users.ivr_last_dialed_at to know who's waited longest
since their last call. sticky_agent's caller->agent mapping lives in Redis
(ivr_routing_service._sticky_key), not a table -- it's a soft affinity, not
a record that needs durability or backup.

Revision ID: 085
Revises: 084
Create Date: 2026-08-23
"""
from alembic import op
import sqlalchemy as sa

revision = "085"
down_revision = "084"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("ivr_last_dialed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_column("users", "ivr_last_dialed_at")
