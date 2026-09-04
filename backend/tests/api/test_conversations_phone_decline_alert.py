"""Tests for the phone-decline alert's conversations.py surface:
- GET /conversations returns has_phone_decline_alert per row
- GET /conversations/{id} returns the open phone_decline_task (or null)
- PATCH /conversations/{id} {assigned_to} -- "Assign to me" on the callout
"""
import uuid

import pytest

from app.models.guest import Guest
from app.models.conversation import Conversation, Message
from app.models.task import Task
from app.models.user import User, UserRole
from app.core.security import get_password_hash


@pytest.fixture()
def auth_headers(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


@pytest.fixture()
def guest(db, tenant_and_user):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_and_user["tenant"].id, phone="+919999000003", name="Neil Moses")
    db.add(g); db.commit()
    return g


@pytest.fixture()
def conv(db, tenant_and_user, guest):
    c = Conversation(
        id=str(uuid.uuid4()), tenant_id=tenant_and_user["tenant"].id, guest_id=guest.id,
        channel="instagram", is_open=True,
    )
    db.add(c); db.commit()
    return c


class TestListHasPhoneDeclineAlert:
    def test_true_when_an_open_task_exists(self, client, db, auth_headers, tenant_and_user, conv):
        task = Task(
            tenant_id=tenant_and_user["tenant"].id, conversation_id=conv.id,
            title="Guest declined phone number — Neil Moses", priority="high",
        )
        db.add(task); db.commit()

        client.headers.update(auth_headers)
        resp = client.get("/api/v1/conversations")
        assert resp.status_code == 200
        row = next(r for r in resp.json() if r["id"] == conv.id)
        assert row["has_phone_decline_alert"] is True

    def test_false_when_no_task(self, client, auth_headers, conv):
        client.headers.update(auth_headers)
        resp = client.get("/api/v1/conversations")
        row = next(r for r in resp.json() if r["id"] == conv.id)
        assert row["has_phone_decline_alert"] is False

    def test_false_once_the_task_is_done(self, client, db, auth_headers, tenant_and_user, conv):
        task = Task(
            tenant_id=tenant_and_user["tenant"].id, conversation_id=conv.id,
            title="Guest declined phone number — Neil Moses", priority="high", is_done=True,
        )
        db.add(task); db.commit()

        client.headers.update(auth_headers)
        resp = client.get("/api/v1/conversations")
        row = next(r for r in resp.json() if r["id"] == conv.id)
        assert row["has_phone_decline_alert"] is False


class TestDetailPhoneDeclineTask:
    def test_returns_the_open_task(self, client, db, auth_headers, tenant_and_user, conv):
        task = Task(
            tenant_id=tenant_and_user["tenant"].id, conversation_id=conv.id,
            title="Guest declined phone number — Neil Moses", priority="high",
        )
        db.add(task); db.commit()

        client.headers.update(auth_headers)
        resp = client.get(f"/api/v1/conversations/{conv.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["phone_decline_task"] is not None
        assert body["phone_decline_task"]["id"] == task.id
        assert body["phone_decline_task"]["title"] == "Guest declined phone number — Neil Moses"

    def test_null_when_no_open_task(self, client, auth_headers, conv):
        client.headers.update(auth_headers)
        resp = client.get(f"/api/v1/conversations/{conv.id}")
        assert resp.json()["phone_decline_task"] is None


class TestAssignConversationToMe:
    def test_patch_assigned_to_sets_owner(self, client, db, auth_headers, tenant_and_user, conv):
        client.headers.update(auth_headers)
        me = tenant_and_user["user"].id
        resp = client.patch(f"/api/v1/conversations/{conv.id}", json={"assigned_to": me})
        assert resp.status_code == 200
        assert resp.json()["assigned_to"] == me

        db.expire_all()
        assert db.get(Conversation, conv.id).assigned_to == me
