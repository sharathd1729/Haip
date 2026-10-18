"""Module activation: the endpoint must queue the task with kwargs the task accepts,
and the task must append to the tenant's audit hash chain (not write a hash-less row).

Regression for: endpoints passed `actor_id=` while the tasks take `activated_by` /
`deactivated_by`, so every activation raised TypeError in the worker; and the tasks wrote
`AuditEvent(hash="")` directly, which would have become the chain tail for the tenant.
"""
import inspect
import uuid
from unittest.mock import patch

import pytest

from app.core.audit import append_audit
from app.models.audit_event import AuditEvent
from app.models.module import Module, WorkspaceModule
from app.workers.tasks.module_activation import activate, deactivate


class _NoCloseSession:
    """Lets the task's own `with SessionLocal() as db:` use the test session."""

    def __init__(self, real_session):
        self._s = real_session

    def __getattr__(self, name):
        return getattr(self._s, name)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def module_row(db):
    mod = Module(id=str(uuid.uuid4()), code=f"t_{uuid.uuid4().hex[:8]}", name="Test module")
    db.add(mod)
    db.commit()
    return mod


def _auth(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.mark.parametrize(
    "method,path,task",
    [("post", "/api/v1/workspace/modules/{code}/activate", "activate"),
     ("delete", "/api/v1/workspace/modules/{code}", "deactivate")],
)
def test_endpoint_queues_task_with_kwargs_the_task_accepts(client, tenant_and_user, module_row, method, path, task):
    with patch(f"app.workers.tasks.module_activation.{task}") as fake:
        resp = getattr(client, method)(path.format(code=module_row.code), headers=_auth(tenant_and_user))

    assert resp.status_code in (200, 201), resp.text
    fake.delay.assert_called_once()
    kwargs = fake.delay.call_args.kwargs
    # Raises TypeError if the endpoint and the task signature drift apart again.
    real = {"activate": activate, "deactivate": deactivate}[task]
    inspect.signature(real.run).bind(**kwargs)
    assert kwargs["workspace_id"] == tenant_and_user["tenant"].id
    assert kwargs["module_code"] == module_row.code


@pytest.mark.parametrize(
    "method,path,task",
    [("post", "/api/v1/workspace/modules/{code}/activate", "activate"),
     ("delete", "/api/v1/workspace/modules/{code}", "deactivate")],
)
def test_non_owner_cannot_queue_activation(client, db, tenant_and_user, module_row, method, path, task):
    from app.core.security import create_access_token
    from app.models.user import UserRole

    user = tenant_and_user["user"]
    user.role = UserRole.MANAGER
    db.commit()
    token = create_access_token({"sub": user.id, "tenant_id": user.tenant_id, "role": "manager"})

    with patch(f"app.workers.tasks.module_activation.{task}") as fake:
        resp = getattr(client, method)(path.format(code=module_row.code),
                                       headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 403
    fake.delay.assert_not_called()


def test_activate_then_deactivate_writes_a_continuous_audit_chain(db, tenant_and_user, module_row):
    tenant, user = tenant_and_user["tenant"], tenant_and_user["user"]
    prior = append_audit(db, tenant_id=tenant.id, action="test.prior", target_id="x")
    db.commit()

    with patch("app.core.database.SessionLocal", return_value=_NoCloseSession(db)), \
         patch("app.workers.tasks.invalidate_cache.workspace_context.delay"), \
         patch("app.workers.tasks.invalidate_cache.full_workspace.delay"):
        assert activate.run(tenant.id, module_row.code, activated_by=user.id)["action"] == "activated"
        wm = db.query(WorkspaceModule).filter_by(workspace_id=tenant.id, module_id=module_row.id).one()
        assert wm.enabled is True

        assert deactivate.run(tenant.id, module_row.code, deactivated_by=user.id)["action"] == "deactivated"
        db.refresh(wm)
        assert wm.enabled is False

    events = (db.query(AuditEvent).filter_by(tenant_id=tenant.id)
              .filter(AuditEvent.action.in_(["module.activated", "module.deactivated"]))
              .order_by(AuditEvent.created_at).all())
    assert [e.action for e in events] == ["module.activated", "module.deactivated"]
    assert all(e.hash for e in events)
    assert events[0].prev_hash == prior.hash
    assert events[1].prev_hash == events[0].hash
    assert events[0].actor_user_id == user.id


def test_activation_only_touches_the_given_workspace(db, tenant_and_user, module_row):
    from app.models.tenant import Tenant

    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    tenant, user = tenant_and_user["tenant"], tenant_and_user["user"]

    with patch("app.core.database.SessionLocal", return_value=_NoCloseSession(db)), \
         patch("app.workers.tasks.invalidate_cache.workspace_context.delay"):
        activate.run(tenant.id, module_row.code, activated_by=user.id)

    assert db.query(WorkspaceModule).filter_by(workspace_id=other.id, module_id=module_row.id).count() == 0
    assert db.query(AuditEvent).filter_by(tenant_id=other.id, action="module.activated").count() == 0
