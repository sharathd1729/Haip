"""Backfill lead_attribution from historical Instagram DM referrals
(HAIP_Dashboard_Metrics_Plan.md Phase 1, step 1.8)

process_instagram_dm.py has stored `message.channel_metadata->'referral'`
since T0.3, well before lead_attribution existed (migration 067) to read it
into. This is the one-time catch-up: for every Instagram conversation whose
earliest referral-bearing message hasn't already been captured, insert the
row the live ingestion path (Phase 1, step 1.5) now writes going forward.

Idempotent via lead_attribution's unique (tenant_id, conversation_id) index
-- ON CONFLICT DO NOTHING, safe to re-run.

Revision ID: 068
Revises: 067
Create Date: 2026-08-08
"""
from alembic import op
import sqlalchemy as sa

revision = "068"
down_revision = "067"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO lead_attribution (
                id, tenant_id, inquiry_id, conversation_id, guest_id,
                destination_channel, ad_id, source_type, headline, media_type,
                raw_referral, first_message_at, created_at, updated_at
            )
            SELECT
                gen_random_uuid()::text,
                earliest.tenant_id,
                c.inquiry_id,
                earliest.conversation_id,
                c.guest_id,
                'instagram',
                earliest.referral ->> 'ad_id',
                CASE WHEN earliest.referral ->> 'ad_id' IS NOT NULL THEN 'ad' ELSE 'post' END,
                earliest.referral ->> 'headline',
                earliest.referral ->> 'media_type',
                earliest.referral,
                earliest.created_at,
                now(),
                now()
            FROM (
                SELECT DISTINCT ON (m.conversation_id)
                    m.conversation_id, m.tenant_id, m.created_at,
                    m.channel_metadata -> 'referral' AS referral
                FROM messages m
                JOIN conversations c2 ON c2.id = m.conversation_id
                WHERE c2.channel = 'instagram'
                  AND m.channel_metadata -> 'referral' IS NOT NULL
                ORDER BY m.conversation_id, m.created_at ASC
            ) earliest
            JOIN conversations c ON c.id = earliest.conversation_id
            ON CONFLICT (tenant_id, conversation_id) DO NOTHING
            """
        )
    )


def downgrade():
    """Not reversible -- no record of which rows this backfill produced
    versus were written by live ingestion after the fact. Leaving backfilled
    rows in place on downgrade is the safe choice, same reasoning as
    migration 066."""
    pass
