"""Backfill guests.phone from guest_identities for guests missing it

identity_resolution.py only ever backfilled the guests.phone convenience
column at guest CREATION time (_create_guest). A phone/whatsapp_number
signal attached to an ALREADY-EXISTING guest later -- e.g. a guest who
first showed up via Instagram, then later called -- never touched
guests.phone even though the phone was fully resolvable via
guest_identities. list_conversations (and every other list endpoint) reads
guests.phone directly for display, so those guests showed no name AND no
phone number in the inbox despite a valid, high-confidence phone signal
existing. The code path is fixed alongside this migration
(identity_resolution.py's new _backfill_guest_phone helper, called from
both resolve_or_create's Stage 2 probabilistic-match branch and
enrich_guest); this is the one-time catch-up for guests already affected.

For each guest with phone = '', pick their highest-confidence (ties broken
by most-recently-seen) phone or whatsapp_number identity signal and copy
its value onto guests.phone. Idempotent: a guest already backfilled no
longer matches phone = '', so re-running finds nothing left to do.

Revision ID: 066
Revises: 065
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE guests g
            SET phone = best.identity_value
            FROM (
                SELECT DISTINCT ON (gi.guest_id)
                    gi.guest_id, gi.tenant_id, gi.identity_value
                FROM guest_identities gi
                WHERE gi.identity_type IN ('phone', 'whatsapp_number')
                ORDER BY gi.guest_id, gi.confidence DESC, gi.last_seen_at DESC NULLS LAST
            ) best
            WHERE g.id = best.guest_id
              AND g.tenant_id = best.tenant_id
              AND (g.phone IS NULL OR g.phone = '')
            """
        )
    )


def downgrade():
    """Not reversible -- there's no record of which guests.phone rows this
    migration set versus were already correctly populated some other way.
    Leaving the backfilled phone numbers in place on downgrade is the safe
    choice (matches the source-of-truth guest_identities data either way)."""
    pass
