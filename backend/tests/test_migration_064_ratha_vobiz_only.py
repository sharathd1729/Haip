"""Tests for migration 064's logic: Ratha's tenant.ivr_provider flips to
'vobiz' and its Mcube Integration row's status flips to 'disconnected',
idempotently, without touching any other tenant. Exercises the same SQL the
migration runs directly against the test DB (migrations aren't run under the
SQLite test harness -- see conftest.py / test_backfill_voice_conversations_migration.py
for the established pattern)."""
import uuid

from sqlalchemy import text

from app.models.tenant import Tenant
from app.models.integration import Integration
from app.core.encryption import encrypt_credentials


def _run_upgrade(db):
    db.execute(text(
        """
        UPDATE tenants
        SET ivr_provider = 'vobiz'
        WHERE slug = 'ratha' AND (ivr_provider IS DISTINCT FROM 'vobiz')
        """
    ))
    db.execute(text(
        """
        UPDATE integrations
        SET status = 'disconnected'
        WHERE kind = 'mcube'
          AND tenant_id = (SELECT id FROM tenants WHERE slug = 'ratha')
          AND status != 'disconnected'
        """
    ))
    db.commit()


def _make_ratha(db):
    tenant = Tenant(id=str(uuid.uuid4()), name="Ratha", slug="ratha", ivr_provider="mcube")
    db.add(tenant)
    db.commit()
    integration = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant.id, kind="mcube", status="active",
        credentials_kms_blob=encrypt_credentials({"api_key": "x", "webhook_secret": "y"}),
    )
    db.add(integration)
    db.commit()
    return tenant, integration


def test_flips_ratha_ivr_provider_to_vobiz(db):
    tenant, _ = _make_ratha(db)
    _run_upgrade(db)
    db.refresh(tenant)
    assert tenant.ivr_provider == "vobiz"


def test_disconnects_ratha_mcube_integration(db):
    tenant, integration = _make_ratha(db)
    _run_upgrade(db)
    db.refresh(integration)
    assert integration.status == "disconnected"


def test_does_not_touch_other_tenants(db):
    other = Tenant(id=str(uuid.uuid4()), name="Jade", slug="jade", ivr_provider="acefone")
    db.add(other)
    db.commit()

    _run_upgrade(db)

    db.refresh(other)
    assert other.ivr_provider == "acefone"


def test_idempotent_on_second_run(db):
    tenant, integration = _make_ratha(db)
    _run_upgrade(db)
    _run_upgrade(db)
    db.refresh(tenant)
    db.refresh(integration)
    assert tenant.ivr_provider == "vobiz"
    assert integration.status == "disconnected"


def test_noop_when_ratha_tenant_absent(db):
    # Migration must not error on a fresh/test DB with no Ratha row at all.
    _run_upgrade(db)
