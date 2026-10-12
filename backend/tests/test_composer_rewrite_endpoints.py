"""Tests for the composer/rewrite endpoints (HAIP Inbox full-parity pass,
ticket 5): POST kicks off composer_rewrite.delay and returns a job_id, GET
reads the short-lived cached result back."""
import uuid
from unittest.mock import patch

import pytest

from app.models.conversation import Conversation, ChannelType
from app.models.guest import Guest


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _auth_headers(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


def _make_conversation(db, tenant_id):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Priya", phone="+919999011223")
    db.add(guest); db.commit()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv); db.commit()
    return conv


@pytest.mark.usefixtures("capabilities_seeded")   # the POST is gated by conversations.send
class TestComposerRewriteEndpoint:
    def test_kicks_off_task_and_returns_job_id(self, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        conv = _make_conversation(db, tenant_id)

        with patch("app.workers.tasks.composer_rewrite.composer_rewrite.delay") as mock_delay:
            resp = client.post(
                f"/api/v1/conversations/{conv.id}/composer/rewrite",
                json={"text": "hi is it free", "tone": "formal"},
                headers=_auth_headers(tenant_and_user),
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "rewrite_queued"
        assert body["job_id"]
        assert mock_delay.called
        assert mock_delay.call_args.kwargs["tone"] == "formal"
        assert mock_delay.call_args.kwargs["text"] == "hi is it free"

    def test_rejects_empty_text(self, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        conv = _make_conversation(db, tenant_id)

        resp = client.post(
            f"/api/v1/conversations/{conv.id}/composer/rewrite",
            json={"text": "   "},
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 422

    def test_404_on_unknown_conversation(self, client, tenant_and_user):
        resp = client.post(
            f"/api/v1/conversations/{uuid.uuid4()}/composer/rewrite",
            json={"text": "hi"},
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 404


class TestComposerRewriteStatusEndpoint:
    def test_pending_when_not_yet_cached(self, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        conv = _make_conversation(db, tenant_id)

        with patch("app.core.cache.get_cached", return_value=None):
            resp = client.get(
                f"/api/v1/conversations/{conv.id}/composer/rewrite/{uuid.uuid4()}",
                headers=_auth_headers(tenant_and_user),
            )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "pending"}

    def test_returns_cached_result_when_done(self, client, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        conv = _make_conversation(db, tenant_id)
        job_id = str(uuid.uuid4())

        with patch(
            "app.core.cache.get_cached",
            return_value={"status": "done", "rewritten_text": "Bonjour!"},
        ):
            resp = client.get(
                f"/api/v1/conversations/{conv.id}/composer/rewrite/{job_id}",
                headers=_auth_headers(tenant_and_user),
            )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "done", "rewritten_text": "Bonjour!"}

    def test_404_on_unknown_conversation(self, client, tenant_and_user):
        resp = client.get(
            f"/api/v1/conversations/{uuid.uuid4()}/composer/rewrite/{uuid.uuid4()}",
            headers=_auth_headers(tenant_and_user),
        )
        assert resp.status_code == 404
