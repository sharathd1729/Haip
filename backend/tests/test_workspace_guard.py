"""Workspace redesign Phase 0: a page at /w/<slug>/ sends X-HAIP-Workspace; the API refuses (409 wrong_workspace) when
it names another workspace than the signed-in one, and checks nothing when the header is absent."""
import pytest

from app.models.tenant import Tenant

pytestmark = pytest.mark.usefixtures("capabilities_seeded")


def _h(tu, slug=None):
    h = {"Authorization": f"Bearer {tu['access_token']}"}
    if slug is not None:
        h["X-HAIP-Workspace"] = slug
    return h


def _slug(db, tu):
    t = tu["tenant"]
    tid = t["id"] if isinstance(t, dict) else t.id
    return db.get(Tenant, tid).slug


def test_own_workspace_and_no_header_pass(client, db, tenant_and_user):
    assert client.get("/api/v1/ops/guest-form/config", headers=_h(tenant_and_user)).status_code == 200
    assert client.get("/api/v1/ops/guest-form/config", headers=_h(tenant_and_user, _slug(db, tenant_and_user))).status_code == 200
    assert client.get("/api/v1/ops/guest-form/config", headers=_h(tenant_and_user, _slug(db, tenant_and_user).upper())).status_code == 200


def test_another_workspaces_address_is_refused(client, db, tenant_and_user):
    r = client.get("/api/v1/ops/guest-form/config", headers=_h(tenant_and_user, "someone-else"))
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "wrong_workspace" and r.json()["detail"]["workspace"] == _slug(db, tenant_and_user)
    # a write is refused the same way, so a stale tab cannot change the other workspace's data
    r = client.put("/api/v1/ops/guest-form/config", json={}, headers=_h(tenant_and_user, "someone-else"))
    assert r.status_code == 409
