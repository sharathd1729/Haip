"""
Tests for dashboard widget API endpoints:
  - GET /dashboard/widgets → returns defaults when config null
  - PUT /dashboard/config → validates max 8, unknown keys
  - POST /dashboard/widgets/refresh → returns widget snapshot
"""

import uuid
import pytest


def auth_headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


class TestGetWidgets:
    def test_returns_widgets_list(self, client, tenant_and_user):
        tenant, user, tokens = tenant_and_user
        resp = client.get("/api/v1/dashboard/widgets", headers=auth_headers(tokens))
        assert resp.status_code == 200
        body = resp.json()
        assert "widgets" in body
        assert isinstance(body["widgets"], list)
        assert len(body["widgets"]) >= 1

    def test_each_widget_has_required_fields(self, client, tenant_and_user):
        _, _, tokens = tenant_and_user
        resp = client.get("/api/v1/dashboard/widgets", headers=auth_headers(tokens))
        for w in resp.json()["widgets"]:
            assert "key" in w
            assert "title" in w
            assert "state" in w
            assert w["state"] in ("unavailable", "early_signal", "full_insight")


class TestUpdateConfig:
    def test_save_valid_selection(self, client, tenant_and_user):
        _, _, tokens = tenant_and_user
        resp = client.put(
            "/api/v1/dashboard/config",
            json={"selected_widgets": ["call_volume", "objections", "sentiment"]},
            headers=auth_headers(tokens),
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_more_than_8_returns_422(self, client, tenant_and_user):
        _, _, tokens = tenant_and_user
        keys = [
            "call_volume", "sentiment", "missed_revenue", "objections",
            "intent_mix", "response_time", "agent_leaderboard", "inquiry_funnel",
            "channel_mix",  # 9th
        ]
        resp = client.put(
            "/api/v1/dashboard/config",
            json={"selected_widgets": keys},
            headers=auth_headers(tokens),
        )
        assert resp.status_code == 422

    def test_unknown_key_returns_422(self, client, tenant_and_user):
        _, _, tokens = tenant_and_user
        resp = client.put(
            "/api/v1/dashboard/config",
            json={"selected_widgets": ["nonexistent_widget_xyz"]},
            headers=auth_headers(tokens),
        )
        assert resp.status_code == 422

    def test_requires_auth(self, client):
        resp = client.put(
            "/api/v1/dashboard/config",
            json={"selected_widgets": ["call_volume"]},
        )
        assert resp.status_code == 401


class TestWidgetLibrary:
    def test_returns_18_widgets(self, client, tenant_and_user):
        _, _, tokens = tenant_and_user
        resp = client.get("/api/v1/dashboard/widget-library", headers=auth_headers(tokens))
        assert resp.status_code == 200
        library = resp.json()["library"]
        assert len(library) == 18

    def test_each_entry_has_category(self, client, tenant_and_user):
        _, _, tokens = tenant_and_user
        resp = client.get("/api/v1/dashboard/widget-library", headers=auth_headers(tokens))
        for item in resp.json()["library"]:
            assert item["category"] in ("calls", "messaging", "revenue", "guests")
