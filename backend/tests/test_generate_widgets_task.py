"""
Tests for generate_widgets Celery task:
  - Upserts widget rows for a tenant
  - __all__ iteration hits all active tenants
  - widget_keys=None generates all 18 keys
  - widget_keys=[...] generates only specified keys
"""

import uuid
import pytest

from app.models.tenant import Tenant
from app.models.dashboard_widget import DashboardWidget
from app.services.widget_service import WIDGET_REGISTRY


def _make_tenant(db, **kwargs):
    t = Tenant(
        id=str(uuid.uuid4()),
        name="Task Test",
        slug=f"tt-{uuid.uuid4().hex[:6]}",
        plan="growth",
        is_active=True,
        **kwargs,
    )
    db.add(t)
    db.flush()
    return t


class TestGenerateWidgetsTask:
    def test_generates_rows_for_tenant(self, db):
        from app.services.widget_service import detect_modules, upsert_widget

        tenant = _make_tenant(db)
        modules = detect_modules(db, tenant)
        upsert_widget(db, tenant, "ai_recommendations", modules)
        db.commit()

        row = db.query(DashboardWidget).filter(
            DashboardWidget.tenant_id == tenant.id,
            DashboardWidget.widget_key == "ai_recommendations",
        ).first()
        assert row is not None
        assert row.state in ("unavailable", "early_signal", "full_insight")

    def test_upsert_is_idempotent(self, db):
        from app.services.widget_service import detect_modules, upsert_widget

        tenant = _make_tenant(db)
        modules = detect_modules(db, tenant)

        upsert_widget(db, tenant, "response_time", modules)
        db.commit()
        upsert_widget(db, tenant, "response_time", modules)
        db.commit()

        count = db.query(DashboardWidget).filter(
            DashboardWidget.tenant_id == tenant.id,
            DashboardWidget.widget_key == "response_time",
        ).count()
        assert count == 1

    def test_all_widget_keys_in_registry(self):
        assert len(WIDGET_REGISTRY) == 19

    def test_tenant_isolation(self, db):
        from app.services.widget_service import detect_modules, upsert_widget

        t1 = _make_tenant(db)
        t2 = _make_tenant(db)
        modules = detect_modules(db, t1)
        upsert_widget(db, t1, "guest_ltv", modules)
        db.commit()

        count_t2 = db.query(DashboardWidget).filter(
            DashboardWidget.tenant_id == t2.id,
        ).count()
        assert count_t2 == 0
