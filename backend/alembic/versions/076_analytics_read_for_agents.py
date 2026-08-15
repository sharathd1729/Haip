"""Role-aware dashboard rebuild: grant 'analytics.read' capability to the
concierge/foh roles for every existing tenant.

authz_service.py's _DEFAULT_GRANTS only provisions capabilities for NEW
tenants going forward -- existing tenants' role_capabilities rows were
seeded at migration 057 and don't retroactively pick up dict changes.
Without this, concierge/foh users would still 403 on the new /dashboard/
overview endpoint despite the code change, since the DB-side matrix (what
get_capabilities() actually reads) never got the grant.

Data-only: inserts one role_capabilities row per (tenant, role) pair for
role in ('concierge', 'foh'), capability_key='analytics.read', allowed=true
-- skips any tenant/role pair that already has a row (idempotent, matches
the unique constraint uq_role_capabilities_tenant_role_key).

Revision ID: 076
Revises: 075
Create Date: 2026-08-16
"""
from alembic import op
import sqlalchemy as sa

revision = "076"
down_revision = "075"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text(
        """
        INSERT INTO role_capabilities (id, tenant_id, role, capability_key, allowed, created_at, updated_at)
        SELECT gen_random_uuid()::text, t.id, r.role, 'analytics.read', true, now(), now()
        FROM tenants t
        CROSS JOIN (VALUES ('concierge'), ('foh')) AS r(role)
        WHERE NOT EXISTS (
            SELECT 1 FROM role_capabilities rc
            WHERE rc.tenant_id = t.id AND rc.role = r.role AND rc.capability_key = 'analytics.read'
        )
        """
    ))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text(
        """
        DELETE FROM role_capabilities
        WHERE capability_key = 'analytics.read' AND role IN ('concierge', 'foh')
        """
    ))
