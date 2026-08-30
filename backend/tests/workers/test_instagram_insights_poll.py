"""
Tests for the daily organic Instagram insights snapshot.

Confirmed live against Ratha's real connected account: reach and
follower_count both return real values via
GET /{ig_account_id}/insights?metric=reach,profile_views,follower_count.
Meta can silently omit a metric from the response rather than erroring
the whole call, so the snapshot must tolerate a partial result.
"""
import uuid
from unittest.mock import patch

from sqlalchemy import text

from app.core.encryption import encrypt_credentials
from app.models.integration import Integration
from app.workers.tasks.instagram_insights_poll import poll_all_tenants


def _tenant_id(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _make_integration(db, tenant_id, ig_account_id="ig-account-1", access_token="real-token"):
    integ = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant_id, kind="instagram", status="active",
        config={"instagram_business_account_id": ig_account_id},
        credentials_kms_blob=encrypt_credentials({"access_token": access_token}),
    )
    db.add(integ); db.commit()
    return integ


def _snapshot_row(db, tenant_id: str):
    return db.execute(
        text("SELECT reach, profile_views, follower_count FROM instagram_insights_snapshots WHERE tenant_id = :tid"),
        {"tid": tenant_id},
    ).first()


class TestPollAllTenants:
    def test_stores_a_snapshot_with_all_metrics_present(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        _make_integration(db, tenant_id)

        api_response = {"data": [
            {"name": "reach", "period": "day", "values": [{"value": 40}, {"value": 55}]},
            {"name": "profile_views", "period": "day", "values": [{"value": 12}]},
            {"name": "follower_count", "period": "day", "values": [{"value": 3}]},
        ]}

        with patch("app.workers.tasks.instagram_insights_poll.SessionLocal", return_value=db), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter._get", return_value=api_response):
            result = poll_all_tenants.run()

        assert result["tenants_polled"] == 1
        row = _snapshot_row(db, tenant_id)
        assert row.reach == 55  # last value in the series, not the first
        assert row.profile_views == 12
        assert row.follower_count == 3

    def test_tolerates_a_metric_meta_silently_omitted(self, db, tenant_and_user):
        """Confirmed live: Meta can drop a requested metric from the
        response entirely instead of erroring -- must not crash the whole
        snapshot over one missing metric."""
        tenant_id = _tenant_id(tenant_and_user)
        _make_integration(db, tenant_id)

        api_response = {"data": [
            {"name": "reach", "period": "day", "values": [{"value": 55}]},
            {"name": "follower_count", "period": "day", "values": [{"value": 3}]},
        ]}

        with patch("app.workers.tasks.instagram_insights_poll.SessionLocal", return_value=db), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter._get", return_value=api_response):
            result = poll_all_tenants.run()

        assert result["tenants_polled"] == 1
        row = _snapshot_row(db, tenant_id)
        assert row.reach == 55
        assert row.profile_views is None
        assert row.follower_count == 3

    def test_no_credentials_blob_skips_without_error(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        integ = Integration(
            id=str(uuid.uuid4()), tenant_id=tenant_id, kind="instagram", status="active",
            config={"instagram_business_account_id": "ig-account-1"},
        )
        db.add(integ); db.commit()

        with patch("app.workers.tasks.instagram_insights_poll.SessionLocal", return_value=db):
            result = poll_all_tenants.run()

        assert result["tenants_polled"] == 1  # attempted, not an error
        assert _snapshot_row(db, tenant_id) is None

    def test_api_error_does_not_crash_the_whole_poll(self, db, tenant_and_user):
        import httpx
        from unittest.mock import MagicMock

        tenant_id = _tenant_id(tenant_and_user)
        _make_integration(db, tenant_id)

        response = MagicMock(status_code=403, text="permission error")
        error = httpx.HTTPStatusError("error", request=MagicMock(), response=response)

        with patch("app.workers.tasks.instagram_insights_poll.SessionLocal", return_value=db), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter._get", side_effect=error):
            result = poll_all_tenants.run()

        assert result["tenants_polled"] == 1
        assert _snapshot_row(db, tenant_id) is None
