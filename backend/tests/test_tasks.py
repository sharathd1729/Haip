"""Tests for HAIP Inbox prototype-wiring plan, ticket 1: the Task model."""
import uuid

from app.models.tenant import Tenant
from app.services import task_service


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _auth_headers(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


class TestTaskServiceHappyPath:
    def test_create_list_toggle_roundtrip(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        conv_id = str(uuid.uuid4())

        task = task_service.create_task(
            db, tenant_id=tenant_id, title="Follow up tomorrow", conversation_id=conv_id,
        )
        assert task.is_done is False

        tasks = task_service.list_tasks(db, tenant_id=tenant_id, conversation_id=conv_id)
        assert len(tasks) == 1
        assert tasks[0].id == task.id

        toggled = task_service.toggle_task(db, tenant_id=tenant_id, task_id=task.id)
        assert toggled.is_done is True
        assert toggled.completed_at is not None

        toggled_back = task_service.toggle_task(db, tenant_id=tenant_id, task_id=task.id)
        assert toggled_back.is_done is False
        assert toggled_back.completed_at is None


class TestTaskServiceTenantIsolation:
    def test_toggle_across_tenant_returns_none(self, db, tenant_and_user):
        tenant_a = _tenant_id(tenant_and_user)
        tenant_b = str(uuid.uuid4())
        db.add(Tenant(id=tenant_b, name="Other Tenant", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth"))
        db.commit()

        task = task_service.create_task(db, tenant_id=tenant_b, title="Tenant B task", guest_id=str(uuid.uuid4()))

        result = task_service.toggle_task(db, tenant_id=tenant_a, task_id=task.id)
        assert result is None

    def test_list_scoped_to_tenant(self, db, tenant_and_user):
        tenant_a = _tenant_id(tenant_and_user)
        tenant_b = str(uuid.uuid4())
        db.add(Tenant(id=tenant_b, name="Other Tenant 2", slug=f"other2-{uuid.uuid4().hex[:6]}", plan="growth"))
        db.commit()

        guest_id = str(uuid.uuid4())  # same value used across both tenants on purpose
        task_service.create_task(db, tenant_id=tenant_a, title="A's task", guest_id=guest_id)
        task_service.create_task(db, tenant_id=tenant_b, title="B's task", guest_id=guest_id)

        tasks_a = task_service.list_tasks(db, tenant_id=tenant_a, guest_id=guest_id)
        assert len(tasks_a) == 1
        assert tasks_a[0].title == "A's task"


class TestTaskEndpoints:
    def test_create_requires_entity_ref(self, client, tenant_and_user):
        resp = client.post(
            "/api/v1/tasks",
            json={"title": "No entity ref"},
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 422

    def test_create_list_toggle_happy_path(self, client, tenant_and_user):
        conv_id = str(uuid.uuid4())
        create_resp = client.post(
            "/api/v1/tasks",
            json={"title": "Call back at 5pm", "conversation_id": conv_id, "priority": "high"},
            headers=_auth_headers(tenant_and_user),
        )
        assert create_resp.status_code == 201, create_resp.text
        task_id = create_resp.json()["id"]

        list_resp = client.get(
            f"/api/v1/tasks?conversation_id={conv_id}",
            headers=_auth_headers(tenant_and_user),
        )
        assert list_resp.status_code == 200
        assert len(list_resp.json()) == 1

        toggle_resp = client.patch(
            f"/api/v1/tasks/{task_id}",
            headers=_auth_headers(tenant_and_user),
        )
        assert toggle_resp.status_code == 200
        assert toggle_resp.json()["is_done"] is True

    def test_toggle_unknown_task_404(self, client, tenant_and_user):
        resp = client.patch(
            f"/api/v1/tasks/{uuid.uuid4()}",
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 404

    def test_cross_tenant_toggle_404s(self, client, db, tenant_and_user):
        other_tenant_id = str(uuid.uuid4())
        db.add(Tenant(id=other_tenant_id, name="Other Tenant 3", slug=f"other3-{uuid.uuid4().hex[:6]}", plan="growth"))
        db.commit()
        other_task = task_service.create_task(
            db, tenant_id=other_tenant_id, title="Other tenant's task", guest_id=str(uuid.uuid4()),
        )

        resp = client.patch(
            f"/api/v1/tasks/{other_task.id}",
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 404
