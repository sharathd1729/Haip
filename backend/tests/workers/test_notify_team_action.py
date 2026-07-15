"""
WhatsApp module Phase 3, T3.3 -- notify_team is now in-app only (push +
SSE), per explicit scoping confirmation, replacing the old
WhatsApp-number-required behavior that no-op'd whenever "to" wasn't
configured.
"""
import uuid
from unittest.mock import patch
import pytest

from app.models.tenant import Tenant
from app.workers.tasks.automation_engine import dispatch_action


def _make_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def test_notify_team_sends_push_and_sse(db):
    t = _make_tenant(db)

    with patch("app.services.push_service.send_to_tenant") as mock_push, \
         patch("redis.Redis.from_url") as mock_redis_from_url:
        mock_redis = mock_redis_from_url.return_value
        detail = dispatch_action(
            db, "notify_team", {"title": "Escalation", "message": "Guest needs a callback"},
            {"conversation_id": "conv-1"}, t.id,
        )

    assert "Escalation" in detail
    mock_push.assert_called_once()
    push_kwargs = mock_push.call_args.kwargs
    assert push_kwargs["title"] == "Escalation"
    assert push_kwargs["body"] == "Guest needs a callback"
    mock_redis.publish.assert_called_once()
    channel, payload = mock_redis.publish.call_args.args
    assert channel == f"sse:{t.id}"
    assert "team_alert" in payload


def test_notify_team_no_longer_requires_whatsapp_number(db):
    """The old behavior no-op'd entirely without cfg["to"] -- now it
    always delivers in-app regardless of any WhatsApp config."""
    t = _make_tenant(db)
    with patch("app.services.push_service.send_to_tenant") as mock_push, \
         patch("redis.Redis.from_url"):
        detail = dispatch_action(db, "notify_team", {}, {}, t.id)
    assert "notification logged" not in detail
    mock_push.assert_called_once()
