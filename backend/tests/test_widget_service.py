"""
Tests for widget_service.py:
  - detect_modules
  - compute_widget_state (min_rows threshold)
  - get_default_widgets (profile routing)
"""

import uuid
import pytest

from app.services.widget_service import (
    detect_modules, compute_widget_state, get_default_widgets, WIDGET_REGISTRY,
)
from app.models.tenant import Tenant


def _make_tenant(db, clear_ivr=False, **kwargs):
    t = Tenant(
        id=str(uuid.uuid4()),
        name="Widget Test",
        slug=f"wt-{uuid.uuid4().hex[:6]}",
        plan="growth",
        **kwargs,
    )
    db.add(t)
    db.flush()
    if clear_ivr:
        # server_default="callerdesk" fires at DB level; override it explicitly
        db.execute(
            __import__("sqlalchemy").text("UPDATE tenants SET voice_platform = NULL WHERE id = :id"),
            {"id": t.id},
        )
        db.refresh(t)
    return t


class TestDetectModules:
    def test_fresh_tenant_no_modules(self, db):
        tenant = _make_tenant(db, clear_ivr=True)
        modules = detect_modules(db, tenant)
        assert "ivr" not in modules
        assert "whatsapp" not in modules

    def test_ivr_detected_when_voice_platform_set(self, db):
        tenant = _make_tenant(db, voice_platform="callerdesk")
        modules = detect_modules(db, tenant)
        assert "ivr" in modules

    def test_whatsapp_detected_when_phone_number_id_set(self, db):
        tenant = _make_tenant(db, whatsapp_phone_number_id="1234567890")
        modules = detect_modules(db, tenant)
        assert "whatsapp" in modules


class TestComputeWidgetState:
    def test_unavailable_when_required_module_missing(self, db):
        tenant = _make_tenant(db, clear_ivr=True)  # no IVR
        modules = detect_modules(db, tenant)
        state = compute_widget_state(db, tenant, "call_volume", modules)
        assert state == "unavailable"

    def test_early_signal_when_insufficient_data(self, db):
        tenant = _make_tenant(db, voice_platform="callerdesk")
        modules = detect_modules(db, tenant)
        # No calls in DB → below min_rows threshold
        state = compute_widget_state(db, tenant, "call_volume", modules)
        assert state == "early_signal"

    def test_full_insight_when_no_rows_required(self, db):
        tenant = _make_tenant(db)
        modules = detect_modules(db, tenant)
        # ai_recommendations has min_rows=0
        state = compute_widget_state(db, tenant, "ai_recommendations", modules)
        assert state == "full_insight"

    def test_unknown_key_returns_unavailable(self, db):
        tenant = _make_tenant(db)
        modules: set[str] = set()
        state = compute_widget_state(db, tenant, "nonexistent_widget", modules)
        assert state == "unavailable"


class TestGetDefaultWidgets:
    def test_fresh_tenant_gets_fresh_defaults(self):
        defaults = get_default_widgets(set())
        assert "ai_recommendations" in defaults
        assert len(defaults) >= 3

    def test_ivr_only_gets_call_widgets(self):
        defaults = get_default_widgets({"ivr"})
        assert "call_volume" in defaults
        assert "objections" in defaults

    def test_wa_only_gets_messaging_widgets(self):
        defaults = get_default_widgets({"whatsapp"})
        assert "channel_mix" in defaults
        assert "response_time" in defaults

    def test_full_stack_gets_mixed_widgets(self):
        defaults = get_default_widgets({"ivr", "whatsapp", "bookings", "properties"})
        assert "call_volume" in defaults
        assert "occupancy_forecast" in defaults

    def test_all_default_keys_in_registry(self):
        for profile_modules in [set(), {"ivr"}, {"whatsapp"}, {"ivr", "whatsapp", "bookings", "properties"}]:
            for key in get_default_widgets(profile_modules):
                assert key in WIDGET_REGISTRY, f"{key} not in registry"
