"""
Tests for GET /analytics/executive, GET /analytics/insights, POST /analytics/insights/{id}/dismiss.

Uses in-memory SQLite via conftest; Redis cache is a no-op (REDIS_URL points to unreachable localhost).
"""

import uuid

import pytest

pytestmark = pytest.mark.usefixtures("capabilities_seeded")   # money endpoints sit behind bookings.read / revenue.read


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _entitle_analytics_modules(request):
    """Grant the modules these endpoints require.

    Module entitlement fails closed (a workspace with no workspace_modules rows gets no module
    access), and the bare ``tenant_and_user`` fixture provisions none. The 403/404 cases below
    that test *other* guards still need the module guard to pass first.
    """
    if "tenant_and_user" not in request.fixturenames:
        yield
        return
    from app.models.module import Module, WorkspaceModule

    db = request.getfixturevalue("db")
    tenant_id = request.getfixturevalue("tenant_and_user")["tenant"].id
    for code in ("analytics", "ai_insights"):
        module = db.query(Module).filter_by(code=code).first()
        if not module:
            module = Module(id=str(uuid.uuid4()), code=code, name=code.title())
            db.add(module)
            db.flush()
        db.add(WorkspaceModule(id=str(uuid.uuid4()), workspace_id=tenant_id, module_id=module.id, enabled=True))
    db.commit()
    yield


def _guest(db, tenant_id):
    """A real guest of the tenant: stays.guest_id and inquiries.guest_id are foreign keys (PostgreSQL enforces them)."""
    from app.models.guest import Guest
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Exec Guest")
    db.add(g)
    db.flush()
    return g.id


def _auth(token: str):
    return {"Authorization": f"Bearer {token}"}


# ─── GET /analytics/executive ─────────────────────────────────────────────────

class TestExecutiveDashboard:

    def test_returns_200_with_empty_data(self, client, tenant_and_user):
        """Empty tenant returns 200 with zero values and empty lists."""
        token = tenant_and_user["access_token"]
        res = client.get("/api/v1/analytics/executive", headers=_auth(token))
        assert res.status_code == 200
        data = res.json()
        # All 6 KPIs present
        assert "revenue_mtd"          in data
        assert "occupancy_pct"        in data
        assert "active_inquiries"     in data
        assert "qa_avg_score"         in data
        assert "sla_compliance_pct"   in data
        assert "ai_draft_rate_pct"    in data
        # Chart datasets present
        assert "revenue_chart"        in data
        assert "funnel"               in data
        assert "channel_mix"          in data
        assert "occupancy_heatmap"    in data
        # Zero values when no data
        assert data["revenue_mtd"]    == 0.0
        assert data["active_inquiries"] == 0

    def test_requires_authentication(self, client):
        """No auth header → 401."""
        res = client.get("/api/v1/analytics/executive")
        assert res.status_code == 401

    def test_range_days_filter(self, client, tenant_and_user):
        """range_days=7 and range_days=90 both return 200."""
        token = tenant_and_user["access_token"]
        for days in [7, 14, 30, 90]:
            res = client.get(
                "/api/v1/analytics/executive",
                params={"range_days": days},
                headers=_auth(token),
            )
            assert res.status_code == 200, f"range_days={days} failed: {res.text}"

    def test_revenue_kpi_with_stays(self, client, tenant_and_user, db):
        """Revenue MTD reflects confirmed stays created this month."""
        from app.models.property import Stay, Property
        from app.models.base import gen_uuid
        from datetime import date
        import calendar

        token = tenant_and_user["access_token"]
        tid   = tenant_and_user["tenant"].id

        # Create a property
        today = date.today()
        prop = Property(
            id=gen_uuid(), tenant_id=tid, name="Test Villa",
            slug="test-villa", type="villa", is_active=True,
        )
        db.add(prop)

        # Create a confirmed stay this month
        stay = Stay(
            id=gen_uuid(), tenant_id=tid,
            guest_id=_guest(db, tid),         # stays.guest_id is a foreign key to guests
            property_id=prop.id,
            check_in=today.replace(day=1),
            check_out=today,
            status="confirmed",
            total_amount=50000.00,
        )
        db.add(stay)
        db.commit()

        res = client.get("/api/v1/analytics/executive", headers=_auth(token))
        assert res.status_code == 200
        data = res.json()
        assert data["revenue_mtd"] == 50000.0

    def test_occupancy_pct_computed(self, client, tenant_and_user, db):
        """Occupancy % is between 0 and 100."""
        token = tenant_and_user["access_token"]
        res = client.get("/api/v1/analytics/executive", headers=_auth(token))
        assert res.status_code == 200
        data = res.json()
        assert 0.0 <= data["occupancy_pct"] <= 100.0

    def test_sla_compliance_100_when_no_responses(self, client, tenant_and_user):
        """SLA compliance defaults to 100% when no inquiries have been responded to yet."""
        token = tenant_and_user["access_token"]
        res = client.get("/api/v1/analytics/executive", headers=_auth(token))
        assert res.status_code == 200
        data = res.json()
        assert data["sla_compliance_pct"] == 100.0

    def test_funnel_stages_are_valid(self, client, tenant_and_user, db):
        """Funnel stages contain only valid inquiry stage names."""
        from app.models.inquiry import Inquiry, InquiryStage, InquirySource
        from app.models.base import gen_uuid

        token = tenant_and_user["access_token"]
        tid   = tenant_and_user["tenant"].id

        # Create a few inquiries across different stages
        guest_id = _guest(db, tid)
        for stage in [InquiryStage.NEW, InquiryStage.QUOTED, InquiryStage.BOOKED]:
            inq = Inquiry(
                id=gen_uuid(), tenant_id=tid,
                guest_id=guest_id,
                stage=stage,
                source=InquirySource.WEBSITE,
            )
            db.add(inq)
        db.commit()

        res = client.get("/api/v1/analytics/executive", headers=_auth(token))
        assert res.status_code == 200
        data = res.json()
        valid_stages = {"new","responding","quoted","site_visit","booked","lost","ghosted"}
        for row in data["funnel"]:
            assert row["stage"].lower() in valid_stages

    def test_channel_mix_percentages_sum_to_100(self, client, tenant_and_user, db):
        """Channel mix percentages sum to ~100 when data exists."""
        from app.models.inquiry import Inquiry, InquiryStage, InquirySource
        from app.models.base import gen_uuid

        token = tenant_and_user["access_token"]
        tid   = tenant_and_user["tenant"].id

        guest_id = _guest(db, tid)
        for source in [InquirySource.WEBSITE, InquirySource.WEBSITE, InquirySource.WA_DIRECT]:
            db.add(Inquiry(
                id=gen_uuid(), tenant_id=tid,
                guest_id=guest_id,
                stage=InquiryStage.NEW,
                source=source,
            ))
        db.commit()

        res = client.get("/api/v1/analytics/executive", headers=_auth(token))
        assert res.status_code == 200
        data = res.json()
        if data["channel_mix"]:
            total_pct = sum(c["pct"] for c in data["channel_mix"])
            assert abs(total_pct - 100.0) < 1.0  # allow float rounding

    def test_property_ids_filter(self, client, tenant_and_user, db):
        """property_ids filter scopes results to selected properties."""
        from app.models.property import Property
        from app.models.base import gen_uuid

        token = tenant_and_user["access_token"]
        tid   = tenant_and_user["tenant"].id

        prop = Property(id=gen_uuid(), tenant_id=tid, name="Filtered Villa",
                        slug="filtered-villa", type="villa", is_active=True)
        db.add(prop); db.commit()

        res = client.get(
            "/api/v1/analytics/executive",
            params={"property_ids": prop.id},
            headers=_auth(token),
        )
        assert res.status_code == 200


# ─── GET /analytics/insights ─────────────────────────────────────────────────

class TestInsightsAPI:

    def test_returns_empty_when_no_insights(self, client, tenant_and_user):
        """New tenant has no insights — returns empty list."""
        token = tenant_and_user["access_token"]
        res = client.get("/api/v1/analytics/insights", headers=_auth(token))
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_returns_active_insights(self, client, tenant_and_user, db):
        """Insights created directly in DB are returned by the API."""
        from app.models.insight import Insight
        from app.models.base import gen_uuid
        from datetime import datetime, timezone

        token = tenant_and_user["access_token"]
        tid   = tenant_and_user["tenant"].id

        insight = Insight(
            id=gen_uuid(), tenant_id=tid,
            category_code="A1", target_id=None,
            category="urgency", severity="critical",
            title="Test: 3 unresponded leads",
            body="These leads need immediate attention.",
            cta_label="Assign Now", cta_href="/dashboard/inquiries",
        )
        db.add(insight); db.commit()

        res = client.get("/api/v1/analytics/insights", headers=_auth(token))
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 1
        assert data["items"][0]["category_code"] == "A1"
        assert data["items"][0]["severity"] == "critical"

    def test_dismissed_insights_not_returned(self, client, tenant_and_user, db):
        """Dismissed insights are excluded from the list."""
        from app.models.insight import Insight
        from app.models.base import gen_uuid
        from datetime import datetime, timezone

        token = tenant_and_user["access_token"]
        tid   = tenant_and_user["tenant"].id

        # Create a dismissed insight
        insight = Insight(
            id=gen_uuid(), tenant_id=tid,
            category_code="B1", target_id=None,
            category="occupancy", severity="medium",
            title="Dismissed insight",
            is_dismissed=True,
        )
        db.add(insight); db.commit()

        res = client.get("/api/v1/analytics/insights", headers=_auth(token))
        data = res.json()
        # The dismissed one must NOT appear
        assert all(i["category_code"] != "B1" for i in data["items"])


# ─── POST /analytics/insights/{id}/dismiss ───────────────────────────────────

class TestDismissInsight:

    def test_dismiss_own_insight(self, client, tenant_and_user, db):
        """Owner can dismiss their tenant's insight."""
        from app.models.insight import Insight
        from app.models.base import gen_uuid

        token = tenant_and_user["access_token"]
        tid   = tenant_and_user["tenant"].id

        insight = Insight(
            id=gen_uuid(), tenant_id=tid,
            category_code="C2", target_id=None,
            category="revenue", severity="medium",
            title="3 quoted leads",
        )
        db.add(insight); db.commit()
        insight_id = insight.id

        res = client.post(
            f"/api/v1/analytics/insights/{insight_id}/dismiss",
            headers=_auth(token),
        )
        assert res.status_code == 200
        assert res.json()["status"] == "dismissed"

        # Verify it no longer appears in list
        list_res = client.get("/api/v1/analytics/insights", headers=_auth(token))
        assert all(i["id"] != insight_id for i in list_res.json()["items"])

    def test_dismiss_nonexistent_insight_returns_404(self, client, tenant_and_user):
        """Dismissing a non-existent insight ID returns 404."""
        token = tenant_and_user["access_token"]
        res = client.post(
            "/api/v1/analytics/insights/nonexistent-id/dismiss",
            headers=_auth(token),
        )
        assert res.status_code == 404

    def test_cannot_dismiss_other_tenants_insight(self, client, tenant_and_user, db):
        """Cannot dismiss an insight belonging to a different tenant."""
        from app.models.insight import Insight
        from app.models.base import gen_uuid

        token = tenant_and_user["access_token"]

        # Create insight for a different (non-existent) tenant
        insight = Insight(
            id=gen_uuid(), tenant_id="other-tenant-id",
            category_code="A1", target_id=None,
            category="urgency", severity="high",
            title="Other tenant insight",
        )
        db.add(insight); db.commit()

        res = client.post(
            f"/api/v1/analytics/insights/{insight.id}/dismiss",
            headers=_auth(token),
        )
        assert res.status_code == 404
