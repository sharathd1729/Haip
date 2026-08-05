"""Tests for migration 065: 064 only matched slug='ratha', but production's
real tenant slug is 'rathaa' -- 064 silently no-op'd there. 065 matches
slug IN ('ratha', 'rathaa') and reasserts the same end state. Exercises the
same SQL the migration runs directly against the test DB (migrations aren't
run under the SQLite test harness -- see test_migration_064_ratha_vobiz_only.py
for the established pattern)."""
import uuid

from sqlalchemy import text, bindparam

from app.models.tenant import Tenant
from app.models.integration import Integration
from app.core.encryption import encrypt_credentials

_SLUGS = ("ratha", "rathaa")


def _run_upgrade(db):
    db.execute(
        text(
            """
            UPDATE tenants
            SET ivr_provider = 'vobiz'
            WHERE slug IN :slugs AND (ivr_provider IS DISTINCT FROM 'vobiz')
            """
        ).bindparams(bindparam("slugs", expanding=True)),
        {"slugs": list(_SLUGS)},
    )
    db.execute(
        text(
            """
            UPDATE integrations
            SET status = 'disconnected'
            WHERE kind = 'mcube'
              AND tenant_id IN (SELECT id FROM tenants WHERE slug IN :slugs)
              AND status != 'disconnected'
            """
        ).bindparams(bindparam("slugs", expanding=True)),
        {"slugs": list(_SLUGS)},
    )
    db.commit()


def _make_tenant(db, slug, ivr_provider="mcube"):
    tenant = Tenant(id=str(uuid.uuid4()), name=slug, slug=slug, ivr_provider=ivr_provider)
    db.add(tenant)
    db.commit()
    integration = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant.id, kind="mcube", status="active",
        credentials_kms_blob=encrypt_credentials({"api_key": "x", "webhook_secret": "y"}),
    )
    db.add(integration)
    db.commit()
    return tenant, integration


def test_flips_rathaa_ivr_provider_to_vobiz(db):
    """The real production slug -- this is the case 064 missed."""
    tenant, _ = _make_tenant(db, "rathaa")
    _run_upgrade(db)
    db.refresh(tenant)
    assert tenant.ivr_provider == "vobiz"


def test_disconnects_rathaa_mcube_integration(db):
    tenant, integration = _make_tenant(db, "rathaa")
    _run_upgrade(db)
    db.refresh(integration)
    assert integration.status == "disconnected"


def test_still_flips_ratha_too(db):
    """064's original target slug must keep working (e.g. staging)."""
    tenant, _ = _make_tenant(db, "ratha")
    _run_upgrade(db)
    db.refresh(tenant)
    assert tenant.ivr_provider == "vobiz"


def test_does_not_touch_other_tenants(db):
    other = Tenant(id=str(uuid.uuid4()), name="Jade", slug="jade", ivr_provider="acefone")
    db.add(other)
    db.commit()

    _run_upgrade(db)

    db.refresh(other)
    assert other.ivr_provider == "acefone"


def test_idempotent_on_second_run(db):
    tenant, integration = _make_tenant(db, "rathaa")
    _run_upgrade(db)
    _run_upgrade(db)
    db.refresh(tenant)
    db.refresh(integration)
    assert tenant.ivr_provider == "vobiz"
    assert integration.status == "disconnected"


def test_noop_when_no_matching_tenant(db):
    _run_upgrade(db)
