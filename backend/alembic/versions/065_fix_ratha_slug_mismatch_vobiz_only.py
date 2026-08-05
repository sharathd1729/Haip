"""Fix migration 064: real tenant slug is 'rathaa', not 'ratha'

064 matched `WHERE slug = 'ratha'`, which doesn't exist in production --
confirmed live (Vobiz webhook URL for this tenant is
/webhooks/vobiz/rathaa/...). It matched zero rows and silently no-op'd:
tenant.ivr_provider was never actually flipped, so Mcube calls kept showing
in the dashboard after deploy.

Matches slug IN ('ratha', 'rathaa') to be safe against the same
inconsistency that exists elsewhere in this repo's own scripts (some use
'ratha', some 'rathaa') without needing to hardcode which one is canonical.
Reasserts the same end state as 064 -- safe to run even where 064 already
(no-op) ran.

Revision ID: 065
Revises: 064
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa

revision = "065"
down_revision = "064"
branch_labels = None
depends_on = None

_SLUGS = ("ratha", "rathaa")


def upgrade():
    bind = op.get_bind()

    bind.execute(
        sa.text(
            """
            UPDATE tenants
            SET ivr_provider = 'vobiz'
            WHERE slug IN :slugs AND (ivr_provider IS DISTINCT FROM 'vobiz')
            """
        ).bindparams(sa.bindparam("slugs", expanding=True)),
        {"slugs": list(_SLUGS)},
    )

    bind.execute(
        sa.text(
            """
            UPDATE integrations
            SET status = 'disconnected'
            WHERE kind = 'mcube'
              AND tenant_id IN (SELECT id FROM tenants WHERE slug IN :slugs)
              AND status != 'disconnected'
            """
        ).bindparams(sa.bindparam("slugs", expanding=True)),
        {"slugs": list(_SLUGS)},
    )


def downgrade():
    bind = op.get_bind()

    bind.execute(
        sa.text(
            """
            UPDATE integrations
            SET status = 'active'
            WHERE kind = 'mcube'
              AND tenant_id IN (SELECT id FROM tenants WHERE slug IN :slugs)
              AND status = 'disconnected'
            """
        ).bindparams(sa.bindparam("slugs", expanding=True)),
        {"slugs": list(_SLUGS)},
    )

    bind.execute(
        sa.text(
            """
            UPDATE tenants
            SET ivr_provider = 'mcube'
            WHERE slug IN :slugs AND ivr_provider = 'vobiz'
            """
        ).bindparams(sa.bindparam("slugs", expanding=True)),
        {"slugs": list(_SLUGS)},
    )
