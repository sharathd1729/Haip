"""Tests for the owner report's per-agent section (agent-attribution
dashboard/reports plan): daily_report_service.get_agent_breakdown() and
its rendering in daily_report_email.render_daily_report()."""
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from tests.conftest import *  # noqa: F401,F403

from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.call import Call, CallDisposition
from app.core.security import get_password_hash
from app.services import daily_report_service
from app.services.daily_report_email import render_daily_report, render_agent_report_html


@pytest.fixture(autouse=True)
def _no_postgres_lateral_join():
    with patch("app.services.message_metrics.chat_response_by_agent", return_value=[]):
        yield


def _make_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t); db.commit(); return t


def _make_user(db, tenant_id, role=UserRole.CONCIERGE, name="Agent"):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name=name,
        email=f"{uuid.uuid4().hex[:8]}@test.com", hashed_password=get_password_hash("pw"),
        role=role, is_active=True,
    )
    db.add(u); db.commit(); return u


class TestAgentBreakdown:
    def test_owner_and_manager_excluded_only_agents_included(self, db, monkeypatch):
        tenant = _make_tenant(db)
        _make_user(db, tenant.id, role=UserRole.OWNER, name="Owner")
        agent = _make_user(db, tenant.id, name="Agent")
        monkeypatch.setattr(
            "app.services.agent_analytics_service.generate_agent_narrative",
            lambda *a, **k: "Handled a steady day of leads.",
        )

        breakdown = daily_report_service.get_agent_breakdown(db, tenant.id, "2026-08-24")

        assert len(breakdown) == 1
        assert breakdown[0]["agent_name"] == "Agent"
        assert breakdown[0]["narrative"] == "Handled a steady day of leads."

    def test_includes_notable_calls_for_the_day(self, db, monkeypatch):
        tenant = _make_tenant(db)
        agent = _make_user(db, tenant.id, name="Agent")
        monkeypatch.setattr(
            "app.services.agent_analytics_service.generate_agent_narrative",
            lambda *a, **k: "",
        )
        db.add(Call(
            id=str(uuid.uuid4()), tenant_id=tenant.id, agent_id=agent.id,
            ivr_provider="vobiz", ivr_call_id=str(uuid.uuid4()),
            direction="outbound", from_number="+919000000001", to_number="+919000000002",
            ai_disposition=CallDisposition.HOT,
            ai_summary="Guest very interested in a Goa trip.", ai_score=90,
            created_at=datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc),
        ))
        db.commit()

        breakdown = daily_report_service.get_agent_breakdown(db, tenant.id, "2026-08-24")

        assert len(breakdown) == 1
        assert breakdown[0]["notable_calls"][0]["disposition"] == "hot"
        assert "Goa" in breakdown[0]["notable_calls"][0]["summary"]

    def test_one_agent_failing_does_not_break_the_rest(self, db, monkeypatch):
        tenant = _make_tenant(db)
        _make_user(db, tenant.id, name="Agent1")
        _make_user(db, tenant.id, name="Agent2")

        calls = {"n": 0}
        def _flaky_narrative(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return "ok"
        monkeypatch.setattr("app.services.agent_analytics_service.generate_agent_narrative", _flaky_narrative)

        breakdown = daily_report_service.get_agent_breakdown(db, tenant.id, "2026-08-24")

        assert len(breakdown) == 1  # the failing agent is skipped, not the whole report


class TestRenderWithByAgent:
    def test_render_does_not_crash_with_agent_section(self):
        report = {
            "kind": "morning",
            "date": "2026-08-24",
            "backlog_days": 5,
            "metrics": {
                "dms_in": 10, "replies_out": 8, "by_channel": {"whatsapp": 10},
                "new_leads": 3, "qualified_leads": 1, "shared_details": 2,
                "calls_total": 4, "calls_missed": 1, "missed_not_returned": 0,
                "awaiting_reply": 0, "bookings": 1, "revenue": 42000.0, "conversion_rate": 33.3,
            },
            "calls_by_disposition": {"booked": 1},
            "notable_calls": [],
            "lost_today": {"count": 0, "reasons": [], "examples": []},
            "top_waiting": [],
            "insights": [],
            "by_agent": [{
                "agent_name": "Agent",
                "scorecard": {"leads_handled": 3, "calls_answered": 3, "calls_missed": 1, "conversions": 1},
                "notable_calls": [{"disposition": "hot", "summary": "Guest interested in a Goa trip."}],
                "narrative": "Responded quickly and stayed on-topic across all conversations.",
            }],
        }
        html = render_daily_report(report, tenant_name="Ratha", dashboard_url="https://example.com")
        assert "Team performance" in html
        assert "Agent" in html
        assert "Goa" in html


_SAMPLE_LEAD = {
    "inquiry_id": "inq-1", "guest_name": "Ritik Raje", "channel": "instagram",
    "snippet": "anniversary weekend", "when": "2026-08-27T11:05:00+00:00", "status": "booked",
    "intent": "anniversary caravan weekend", "route_mentioned": "Bangalore -> Nandi Hills",
    "guest_count": "2 adults", "quoted_amount": 42000.0, "special_requests": None,
    "upsell_offered": "Sunset photography add-on", "upsell_accepted": True,
    "lead_quality": {"label": "hot"},
    "ai_lead_analysis": "Fast-moving, high-intent guest who accepted the upsell without hesitation.",
}
_SAMPLE_LOST_LEAD = {
    **_SAMPLE_LEAD, "inquiry_id": "inq-2", "guest_name": "Deepa Krishnan", "channel": "call",
    "status": "lost", "upsell_offered": None, "upsell_accepted": None,
    "ai_lead_analysis": "Objected to the day-rate immediately.",
}


class TestOwnerEmailLeadBreakdown:
    def test_top_leads_condensed_with_view_all_link_for_the_rest(self):
        report = {
            "kind": "morning", "date": "2026-08-27", "backlog_days": 5,
            "metrics": {
                "dms_in": 3, "replies_out": 3, "by_channel": {"whatsapp": 2, "instagram": 1},
                "new_leads": 1, "qualified_leads": 0, "shared_details": 0,
                "calls_total": 1, "calls_missed": 0, "missed_not_returned": 0,
                "awaiting_reply": 0, "bookings": 1, "revenue": 42000.0, "conversion_rate": 33.0,
            },
            "calls_by_disposition": {}, "notable_calls": [],
            "lost_today": {"count": 0, "reasons": [], "examples": []},
            "top_waiting": [], "insights": [],
            "by_agent": [{
                "agent_id": "agent-1", "agent_name": "Krisha",
                "scorecard": {"leads_handled": 3, "calls_answered": 1, "calls_missed": 0, "conversions": 1},
                "notable_calls": [], "narrative": "",
                "leads": [_SAMPLE_LEAD, _SAMPLE_LOST_LEAD, {**_SAMPLE_LEAD, "inquiry_id": "inq-3", "status": "progress"}],
            }],
        }
        html = render_daily_report(report, tenant_name="Ratha", dashboard_url="https://example.com")

        assert "Ritik Raje" in html
        assert "Deepa Krishnan" in html
        # the third (in-progress) lead is not decision-relevant enough for
        # the top-2 condensed slots -- only reachable via "View all"
        assert "View all 3 leads" in html
        assert "agent_id=agent-1" in html
        assert "accepted the upsell without hesitation" in html

    def test_two_or_fewer_leads_has_no_view_all_link(self):
        report = {
            "kind": "morning", "date": "2026-08-27", "backlog_days": 5,
            "metrics": {
                "dms_in": 1, "replies_out": 1, "by_channel": {},
                "new_leads": 1, "qualified_leads": 0, "shared_details": 0,
                "calls_total": 0, "calls_missed": 0, "missed_not_returned": 0,
                "awaiting_reply": 0, "bookings": 0, "revenue": 0.0, "conversion_rate": 0.0,
            },
            "calls_by_disposition": {}, "notable_calls": [],
            "lost_today": {"count": 0, "reasons": [], "examples": []},
            "top_waiting": [], "insights": [],
            "by_agent": [{
                "agent_id": "agent-1", "agent_name": "Krisha",
                "scorecard": {"leads_handled": 1, "calls_answered": 0, "calls_missed": 0, "conversions": 0},
                "notable_calls": [], "narrative": "", "leads": [_SAMPLE_LEAD],
            }],
        }
        html = render_daily_report(report, tenant_name="Ratha", dashboard_url="https://example.com")
        assert "View all" not in html


class TestOwnerEmailBookingsChannelsLost:
    def test_bookings_revenue_channel_mix_and_lost_today_render(self):
        report = {
            "kind": "morning", "date": "2026-08-27", "backlog_days": 5,
            "metrics": {
                "dms_in": 3, "replies_out": 3, "by_channel": {"whatsapp": 2, "instagram": 1},
                "new_leads": 1, "qualified_leads": 0, "shared_details": 0,
                "calls_total": 1, "calls_missed": 0, "missed_not_returned": 0,
                "awaiting_reply": 0, "bookings": 1, "revenue": 42000.0, "conversion_rate": 100.0,
            },
            "calls_by_disposition": {"booked": 1, "lost": 1},
            "notable_calls": [{"disposition": "booked", "summary": "Booked a caravan trip.", "duration_seconds": 300}],
            "lost_today": {
                "count": 1, "reasons": [{"reason": "budget_mismatch", "count": 1}],
                "examples": [{"guest_name": "Deepa", "route_mentioned": "Bangalore to Coorg", "quoted_amount": 25000.0, "lost_reason": "budget_mismatch"}],
            },
            "top_waiting": [], "insights": [], "by_agent": [],
        }
        html = render_daily_report(report, tenant_name="Ratha", dashboard_url="https://example.com")

        assert "₹42,000" in html
        assert "Bookings" in html
        assert "Whatsapp" in html and "Instagram" in html
        assert "Booked 1" in html
        assert "1 lead lost" in html
        assert "budget mismatch" in html
        assert "Deepa" in html

    def test_zero_lost_today_renders_nothing(self):
        report = {
            "kind": "morning", "date": "2026-08-27", "backlog_days": 5,
            "metrics": {
                "dms_in": 0, "replies_out": 0, "by_channel": {},
                "new_leads": 0, "qualified_leads": 0, "shared_details": 0,
                "calls_total": 0, "calls_missed": 0, "missed_not_returned": 0,
                "awaiting_reply": 0, "bookings": 0, "revenue": 0.0, "conversion_rate": 0.0,
            },
            "calls_by_disposition": {}, "notable_calls": [],
            "lost_today": {"count": 0, "reasons": [], "examples": []},
            "top_waiting": [], "insights": [], "by_agent": [],
        }
        html = render_daily_report(report, tenant_name="Ratha", dashboard_url="https://example.com")
        assert "Lost today" not in html


class TestAgentEmailLeadBreakdownSummaryFeedback:
    def test_full_lead_cards_summary_and_feedback_render(self):
        block = {
            "agent_id": "agent-1", "agent_name": "Krisha", "date": "2026-08-27",
            "scorecard": {
                "leads_handled": 2, "calls_answered": 1, "calls_missed": 0, "conversions": 1,
                "avg_response_seconds": 120, "followups_completed": 1, "followups_total": 1, "followups_overdue": 0,
            },
            "notable_calls": [], "narrative": "Handled two leads today.",
            "leads": [_SAMPLE_LEAD, _SAMPLE_LOST_LEAD],
            "leads_summary": "One booking with an accepted upsell, one price objection.",
            "leads_feedback": [
                {"type": "good", "text": "Ritik's upsell landed because it was offered mid-conversation."},
                {"type": "improve", "text": "Quote Deepa's day-rate earlier next time."},
            ],
        }
        html = render_agent_report_html(block, tenant_name="Ratha", dashboard_url="https://example.com")

        assert "Lead breakdown" in html
        assert "Bangalore -&gt; Nandi Hills" in html or "Bangalore -> Nandi Hills" in html
        assert "Upsell accepted" in html
        assert "Leads summary" in html
        assert "One booking with an accepted upsell" in html
        assert "Feedback" in html
        assert "upsell landed" in html
        assert "day-rate earlier" in html

    def test_no_leads_renders_no_new_sections(self):
        block = {
            "agent_id": "agent-1", "agent_name": "Krisha", "date": "2026-08-27",
            "scorecard": {
                "leads_handled": 0, "calls_answered": 0, "calls_missed": 0, "conversions": 0,
                "avg_response_seconds": 0, "followups_completed": 0, "followups_total": 0, "followups_overdue": 0,
            },
            "notable_calls": [], "narrative": "", "leads": [], "leads_summary": None, "leads_feedback": [],
        }
        html = render_agent_report_html(block, tenant_name="Ratha", dashboard_url="https://example.com")
        assert "Lead breakdown" not in html
        assert "Leads summary" not in html
        assert "Feedback" not in html
