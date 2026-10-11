"""One health rule for the Dashboard bar, the D3 insight and the Integrations page."""
from datetime import datetime, timedelta, timezone

from app.services import integration_health as ih

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


def _ago(**kw):
    return (NOW - timedelta(**kw)).isoformat()


def test_connected_webhook_channel_is_green_even_if_never_verified():
    # This is the bug: status is "active", last_health_at is old or empty, and it used to show as a fault.
    for kind in ("whatsapp_meta", "instagram", "vobiz", "acefone"):
        assert ih.classify(kind, "active", None, NOW) == ih.GREEN
        assert ih.classify(kind, "active", _ago(days=9), NOW) == ih.GREEN


def test_error_is_red_and_off_states_are_not_faults():
    assert ih.classify("whatsapp_meta", "error", None, NOW) == ih.RED
    assert ih.classify("mcube", "disconnected", None, NOW) == ih.OFF
    assert ih.classify("instagram", "pending", None, NOW) == ih.OFF


def test_polled_sync_degrades_only_when_the_sync_stops():
    assert ih.classify("hostaway", "active", _ago(minutes=50), NOW) == ih.GREEN
    assert ih.classify("hostaway", "active", _ago(hours=5), NOW) == ih.YELLOW
    assert ih.classify("hostaway", "active", _ago(hours=20), NOW) == ih.RED
    assert ih.classify("retalwise", "active", None, NOW) == ih.YELLOW


def test_d3_and_dashboard_endpoint_agree(db, client, tenant_and_user):
    """A tenant whose only integration is a healthy, never-verified Vobiz line has no fault anywhere."""
    from app.models.integration import Integration
    from app.models.insight import Insight
    from app.services.insight_detector import detect_D3

    tenant, tokens = tenant_and_user["tenant"], tenant_and_user
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    db.add(Integration(tenant_id=tenant.id, kind="vobiz", status="active", config={}))
    db.commit()

    detect_D3(db, tenant.id)
    db.commit()
    assert db.query(Insight).filter_by(tenant_id=tenant.id, category_code="D3").count() == 0
    services = client.get("/api/v1/health/dashboard", headers=headers).json()["services"]
    vobiz = next(s for s in services if s["name"] == "vobiz")
    assert vobiz["status"] == "green"

    row = db.query(Integration).filter_by(tenant_id=tenant.id, kind="vobiz").one()
    row.status = "error"
    db.commit()
    detect_D3(db, tenant.id)
    db.commit()
    assert db.query(Insight).filter_by(tenant_id=tenant.id, category_code="D3").count() == 1
    services = client.get("/api/v1/health/dashboard", headers=headers).json()["services"]
    assert next(s for s in services if s["name"] == "vobiz")["status"] == "red"


def test_dashboard_health_hides_integrations_the_owner_turned_off(db, client, tenant_and_user):
    from app.models.integration import Integration

    tenant, tokens = tenant_and_user["tenant"], tenant_and_user
    db.add(Integration(tenant_id=tenant.id, kind="mcube", status="disconnected", config={}))
    db.commit()
    r = client.get("/api/v1/health/dashboard", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert all(s["name"] != "mcube" for s in r.json()["services"])
