"""Disconnect Mcube for Ratha — Vobiz becomes the sole active IVR provider

Ratha is moving off Mcube entirely (Vobiz-only going forward). This does NOT
delete any data: existing Call rows with ivr_provider='mcube' and the Mcube
Integration row both stay in the DB untouched — calls.py's list/detail
endpoints already hide calls whose ivr_provider doesn't match the tenant's
current tenants.ivr_provider, so flipping that one field is what makes the
Mcube recordings drop out of the dashboard. Setting the Integration's status
to 'disconnected' additionally makes webhooks_mcube.py reject any further
inbound webhook posts, even if Mcube's own dashboard is still pointed here.

Reasserts the same end state on every run (create/update, not insert-only),
matching migrations 062/063's per-tenant backfill pattern.

Revision ID: 064
Revises: 063
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    bind.execute(
        sa.text(
            """
            UPDATE tenants
            SET ivr_provider = 'vobiz'
            WHERE slug = 'ratha' AND (ivr_provider IS DISTINCT FROM 'vobiz')
            """
        )
    )

    bind.execute(
        sa.text(
            """
            UPDATE integrations
            SET status = 'disconnected'
            WHERE kind = 'mcube'
              AND tenant_id = (SELECT id FROM tenants WHERE slug = 'ratha')
              AND status != 'disconnected'
            """
        )
    )


def downgrade():
    bind = op.get_bind()

    bind.execute(
        sa.text(
            """
            UPDATE integrations
            SET status = 'active'
            WHERE kind = 'mcube'
              AND tenant_id = (SELECT id FROM tenants WHERE slug = 'ratha')
              AND status = 'disconnected'
            """
        )
    )

    bind.execute(
        sa.text(
            """
            UPDATE tenants
            SET ivr_provider = 'mcube'
            WHERE slug = 'ratha' AND ivr_provider = 'vobiz'
            """
        )
    )
