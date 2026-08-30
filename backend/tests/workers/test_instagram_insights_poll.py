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
        text(
            "SELECT reach, profile_views, follower_count, followers_count, following_count, "
            "media_count, accounts_engaged, total_interactions, likes, comments, shares, saves, "
            "replies, profile_links_taps, demographics "
            "FROM instagram_insights_snapshots WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id},
    ).first()


def _post_rows(db, tenant_id: str):
    return db.execute(
        text(
            "SELECT media_id, caption, like_count, reach, saved, shares "
            "FROM instagram_post_snapshots WHERE tenant_id = :tid"
        ),
        {"tid": tenant_id},
    ).all()


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


class TestExpandedInsights:
    """Account overview, engagement totals, demographics, per-post
    performance -- mocked at the adapter-method level rather than the raw
    _get transport, since meta_graph.py's real request shapes for these
    were already verified live against Ratha's connected account."""

    def test_account_overview_and_engagement_are_stored(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        _make_integration(db, tenant_id)

        with patch("app.workers.tasks.instagram_insights_poll.SessionLocal", return_value=db), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_account_insights",
                   return_value=[{"name": "reach", "values": [{"value": 55}]}]), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_account_fields",
                   return_value={"followers_count": 5022, "follows_count": 2, "media_count": 29}), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_account_engagement_totals",
                   return_value={"likes": 125, "comments": 0, "shares": 8, "saves": 4,
                                 "accounts_engaged": 64, "total_interactions": 145}), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_follower_demographics",
                   return_value=[]), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_recent_media",
                   return_value=[]):
            result = poll_all_tenants.run()

        assert result["tenants_polled"] == 1
        row = _snapshot_row(db, tenant_id)
        assert row.followers_count == 5022
        assert row.following_count == 2
        assert row.media_count == 29
        assert row.likes == 125
        assert row.accounts_engaged == 64
        assert row.total_interactions == 145

    def test_demographics_stored_per_breakdown(self, db, tenant_and_user):
        import json
        tenant_id = _tenant_id(tenant_and_user)
        _make_integration(db, tenant_id)

        city_results = [{"dimension_values": ["Thane, Maharashtra"], "value": 13},
                         {"dimension_values": ["Coimbatore, Tamil Nadu"], "value": 19}]

        with patch("app.workers.tasks.instagram_insights_poll.SessionLocal", return_value=db), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_account_insights", return_value=[]), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_account_fields", return_value={}), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_account_engagement_totals", return_value={}), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_follower_demographics",
                   side_effect=lambda breakdown: city_results if breakdown == "city" else []), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_recent_media", return_value=[]):
            poll_all_tenants.run()

        row = _snapshot_row(db, tenant_id)
        demographics = row.demographics if isinstance(row.demographics, dict) else json.loads(row.demographics)
        assert demographics["city"] == city_results
        assert demographics["country"] == []

    def test_one_missing_demographic_breakdown_does_not_block_the_others(self, db, tenant_and_user):
        """Confirmed live: a small/new account may not clear whatever
        minimum-audience threshold Meta enforces for demographics -- that's
        a real 'not enough data yet' case per breakdown, must not abort the
        whole snapshot."""
        import httpx
        from unittest.mock import MagicMock

        tenant_id = _tenant_id(tenant_and_user)
        _make_integration(db, tenant_id)

        response = MagicMock(status_code=400, text="not enough data")
        error = httpx.HTTPStatusError("error", request=MagicMock(), response=response)

        def _demographics(breakdown):
            if breakdown == "age":
                raise error
            return [{"dimension_values": ["IN"], "value": 100}]

        with patch("app.workers.tasks.instagram_insights_poll.SessionLocal", return_value=db), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_account_insights", return_value=[]), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_account_fields", return_value={}), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_account_engagement_totals", return_value={}), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_follower_demographics", side_effect=_demographics), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_recent_media", return_value=[]):
            result = poll_all_tenants.run()

        assert result["tenants_polled"] == 1
        row = _snapshot_row(db, tenant_id)
        assert row is not None  # snapshot still saved despite the "age" failure

    def test_recent_posts_are_upserted_not_duplicated(self, db, tenant_and_user):
        tenant_id = _tenant_id(tenant_and_user)
        _make_integration(db, tenant_id)

        media = [{"id": "post-1", "caption": "Hi", "media_type": "IMAGE",
                  "permalink": "https://instagram.com/p/1", "timestamp": "2026-08-11T14:45:48+0000",
                  "like_count": 83, "comments_count": 5}]

        def _run_poll(media_insights_return):
            with patch("app.workers.tasks.instagram_insights_poll.SessionLocal", return_value=db), \
                 patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_account_insights", return_value=[]), \
                 patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_account_fields", return_value={}), \
                 patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_account_engagement_totals", return_value={}), \
                 patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_follower_demographics", return_value=[]), \
                 patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_recent_media", return_value=media), \
                 patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_media_insights", return_value=media_insights_return):
                poll_all_tenants.run()

        # First poll: like_count=83, reach=5115
        _run_poll({"reach": 5115, "saved": 4, "shares": 8, "total_interactions": 145})

        # Second poll, same post, engagement grew: must update in place, not add a second row
        media[0]["like_count"] = 90
        _run_poll({"reach": 5200, "saved": 5, "shares": 9, "total_interactions": 150})

        rows = _post_rows(db, tenant_id)
        assert len(rows) == 1
        assert rows[0].like_count == 90
        assert rows[0].reach == 5200

    def test_one_post_insights_failure_does_not_drop_the_rest(self, db, tenant_and_user):
        import httpx
        from unittest.mock import MagicMock

        tenant_id = _tenant_id(tenant_and_user)
        _make_integration(db, tenant_id)

        media = [
            {"id": "post-bad", "caption": "A", "media_type": "IMAGE", "timestamp": "2026-08-10T00:00:00+0000"},
            {"id": "post-good", "caption": "B", "media_type": "IMAGE", "timestamp": "2026-08-11T00:00:00+0000"},
        ]
        response = MagicMock(status_code=400, text="unsupported metric")
        error = httpx.HTTPStatusError("error", request=MagicMock(), response=response)

        def _media_insights(media_id, metrics):
            if media_id == "post-bad":
                raise error
            return {"reach": 100, "saved": 1, "shares": 1, "total_interactions": 5}

        with patch("app.workers.tasks.instagram_insights_poll.SessionLocal", return_value=db), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_account_insights", return_value=[]), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_account_fields", return_value={}), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_account_engagement_totals", return_value={}), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_follower_demographics", return_value=[]), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_recent_media", return_value=media), \
             patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_media_insights", side_effect=_media_insights):
            poll_all_tenants.run()

        rows = {r.media_id: r for r in _post_rows(db, tenant_id)}
        assert set(rows.keys()) == {"post-bad", "post-good"}
        assert rows["post-bad"].reach is None  # insights failed, but the post itself was still saved
        assert rows["post-good"].reach == 100
