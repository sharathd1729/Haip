"""Migration 140: quote options + the quote-builder capabilities for EXISTING tenants (defaults only reach new ones).

  * missing cells are added per the default matrix; an existing cell (an owner's choice) is never changed;
  * an unprovisioned tenant (no matrix) is left alone; one tenant never affects another; a second run changes nothing;
  * the chain is 128 -> 140 and the defaults in authz_service match the migration's.
"""
import importlib.util
import pathlib
import uuid

import pytest

from app.models.capability import Capability, RoleCapability
from app.models.tenant import Tenant
from app.services import authz_service
from tests.conftest import seed_capabilities

MIGRATION = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "140_quote_options_and_capabilities.py"
KEYS = ("quotes.write", "business_data.draft", "business_data.publish")


@pytest.fixture(scope="module")
def mig():
    spec = importlib.util.spec_from_file_location("mig140", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tenant(db, provisioned=True):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"m140-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(t)
    db.commit()
    if provisioned:
        seed_capabilities(db, t.id)
    return t


def _as_before_140(db, tenant_id):
    """A tenant seeded before this change: no cells for the three new keys."""
    db.query(RoleCapability).filter(RoleCapability.tenant_id == tenant_id, RoleCapability.capability_key.in_(KEYS)).delete(synchronize_session=False)
    db.commit()


def _grid(db, tenant_id):
    return {(c.role, c.capability_key): c.allowed for c in db.query(RoleCapability).filter(
        RoleCapability.tenant_id == tenant_id, RoleCapability.capability_key.in_(KEYS))}


def test_defaults_match_the_migration(mig):
    for key, _l, _c, _w, _r, roles in mig.CAPABILITIES:
        assert authz_service._DEFAULT_GRANTS[key] == roles
    assert authz_service._DEFAULT_GRANTS["quotes.write"] == {"owner", "manager", "reservations", "concierge"}
    assert authz_service._DEFAULT_GRANTS["business_data.publish"] == {"owner", "manager"}


def test_existing_tenants_get_the_default_cells_and_owner_choices_are_kept(db, mig):
    old, custom, bare = _tenant(db), _tenant(db), _tenant(db, provisioned=False)
    _as_before_140(db, old.id)
    _as_before_140(db, custom.id)
    db.add(RoleCapability(id=str(uuid.uuid4()), tenant_id=custom.id, role="concierge", capability_key="quotes.write", allowed=False))
    db.commit()
    result = mig.apply_capabilities(db.connection())
    db.expire_all()
    grid = _grid(db, old.id)
    assert len(grid) == len(authz_service._ROLES) * 3
    for (role, key), allowed in grid.items():
        assert allowed == (role in authz_service._DEFAULT_GRANTS[key]), (role, key)
    assert _grid(db, custom.id)[("concierge", "quotes.write")] is False          # the owner's decision stands
    assert _grid(db, bare.id) == {}                                              # unprovisioned: still fails closed
    assert result["cells"] >= 2 * len(authz_service._ROLES) * 3 - 1
    assert {k for (k,) in db.query(Capability.key).filter(Capability.key.in_(KEYS))} == set(KEYS)


def test_a_second_run_changes_nothing(db, mig):
    t = _tenant(db)
    _as_before_140(db, t.id)
    mig.apply_capabilities(db.connection())
    db.expire_all()
    before = _grid(db, t.id)
    again = mig.apply_capabilities(db.connection())
    db.expire_all()
    assert again["catalogue"] == 0 and _grid(db, t.id) == before
    assert db.query(RoleCapability).filter_by(tenant_id=t.id, capability_key="quotes.write").count() == len(authz_service._ROLES)


def test_migration_chain(mig):
    assert mig.revision == "140" and mig.down_revision == "128"
