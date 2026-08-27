"""GET /worklist/briefing -- cache-only read, never an inline LLM call."""
from unittest.mock import patch

from tests.conftest import *  # noqa: F401,F403

from app.services import daily_briefing_service


def _fake_cache(monkeypatch):
    store: dict = {}
    monkeypatch.setattr(daily_briefing_service, "get_cached", lambda key: store.get(key))
    monkeypatch.setattr(daily_briefing_service, "set_cached", lambda key, value, ttl=300: store.__setitem__(key, value))
    return store


def _fake_idem(monkeypatch):
    """Real idem_check_and_set fails open (always True) without a live
    Redis -- which would make the "no double-enqueue" test vacuously pass
    for the wrong reason. Stand in a real once-only in-memory guard."""
    seen: set = set()

    def _check(key, ttl=86400):
        if key in seen:
            return False
        seen.add(key)
        return True

    monkeypatch.setattr("app.core.cache.idem_check_and_set", _check)


class TestBriefingEndpoint:
    def test_cache_miss_returns_unavailable_and_enqueues_generation(self, client, db, monkeypatch, tenant_and_user):
        _fake_cache(monkeypatch)
        headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}

        with patch("app.workers.tasks.daily_briefing.generate_daily_briefing") as mock_task:
            resp = client.get("/api/v1/worklist/briefing", headers=headers)

        assert resp.status_code == 200
        assert resp.json() == {"available": False}
        mock_task.delay.assert_called_once()

    def test_second_poll_within_guard_window_does_not_reenqueue(self, client, db, monkeypatch, tenant_and_user):
        _fake_cache(monkeypatch)
        _fake_idem(monkeypatch)
        headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}

        with patch("app.workers.tasks.daily_briefing.generate_daily_briefing") as mock_task:
            client.get("/api/v1/worklist/briefing", headers=headers)
            client.get("/api/v1/worklist/briefing", headers=headers)

        assert mock_task.delay.call_count == 1

    def test_cache_hit_returns_the_cached_briefing(self, client, db, monkeypatch, tenant_and_user):
        store = _fake_cache(monkeypatch)
        tenant_id = tenant_and_user["tenant"]["id"] if isinstance(tenant_and_user["tenant"], dict) else tenant_and_user["tenant"].id
        store[daily_briefing_service._cache_key(tenant_id)] = {
            "narrative": "All clear.", "flags": [], "generated_at": "2026-08-27T00:00:00+00:00",
        }
        headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}

        with patch("app.workers.tasks.daily_briefing.generate_daily_briefing") as mock_task:
            resp = client.get("/api/v1/worklist/briefing", headers=headers)

        assert resp.status_code == 200
        body = resp.json()
        assert body["available"] is True
        assert body["narrative"] == "All clear."
        mock_task.delay.assert_not_called()
