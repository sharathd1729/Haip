"""Phone-decline visibility in the report emails: owner daily report, agent
EOD report, and the 3x-daily agent worklist email should all surface open
"Guest declined phone number" Tasks (with a Profile 360 deep link), not
just the push/Task/badge from a213a5b/3f4a7ba.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.conversation import Conversation, ChannelType
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.models.task import Task
from app.models.user import User, UserRole
from app.core.security import get_password_hash
from app.services import daily_report_service as drs
from app.services import phone_decline_detector
from app.services.daily_report_email import render_daily_report, render_agent_report_html
from app.services.agent_worklist_email import render_agent_worklist_html
from app.services.date_presets import IST


@pytest.fixture(autouse=True)
def _no_postgres_lateral_join():
    """agent_analytics_service's scorecard query uses IS DISTINCT FROM
    (Postgres-only) -- same workaround test_daily_report_agent_breakdown.py
    uses, needed only for the agent-report tests below."""
    with patch("app.services.message_metrics.chat_response_by_agent", return_value=[]):
        yield


def _tenant(db):
    t = Tenant(name="R", slug=f"r-{uuid.uuid4().hex[:8]}")
    db.add(t); db.commit()
    return t


def _agent(db, tenant_id, name="Krishna"):
    u = User(
        tenant_id=tenant_id, name=name, email=f"{uuid.uuid4().hex[:8]}@test.com",
        hashed_password=get_password_hash("pw"), role=UserRole.CONCIERGE, is_active=True,
    )
    db.add(u); db.commit()
    return u


def _declined_lead(db, tenant, *, assigned_to=None, name="Neil Moses"):
    guest = Guest(tenant_id=tenant.id, name=name)
    db.add(guest); db.flush()
    conv = Conversation(
        tenant_id=tenant.id, guest_id=guest.id, channel=ChannelType.INSTAGRAM,
        is_open=True, assigned_to=assigned_to,
    )
    db.add(conv); db.flush()
    task = Task(
        tenant_id=tenant.id, conversation_id=conv.id, guest_id=guest.id,
        title=f"Guest declined phone number — {name}", priority="high",
    )
    db.add(task); db.commit()
    return guest, conv, task


class TestOpenTasksHelper:
    def test_finds_open_tenant_wide_task(self, db):
        t = _tenant(db)
        guest, conv, task = _declined_lead(db, t)
        found = phone_decline_detector.open_tasks(db, t.id)
        assert len(found) == 1
        assert found[0]["guest_id"] == guest.id
        assert found[0]["guest_name"] == "Neil Moses"

    def test_ignores_done_tasks(self, db):
        t = _tenant(db)
        guest, conv, task = _declined_lead(db, t)
        task.is_done = True
        db.commit()
        assert phone_decline_detector.open_tasks(db, t.id) == []

    def test_scopes_to_one_agent_via_conversation_assignment(self, db):
        t = _tenant(db)
        agent1 = _agent(db, t.id, "Krishna")
        agent2 = _agent(db, t.id, "Jishanth")
        _declined_lead(db, t, assigned_to=agent1.id, name="Assigned To Krishna")
        _declined_lead(db, t, assigned_to=agent2.id, name="Assigned To Jishanth")

        found = phone_decline_detector.open_tasks(db, t.id, agent_id=agent1.id)
        assert len(found) == 1
        assert found[0]["guest_name"] == "Assigned To Krishna"


class TestOwnerReportPhoneDeclines:
    def test_report_carries_phone_declines_with_guest_id(self, db):
        t = _tenant(db)
        guest, conv, task = _declined_lead(db, t)
        report = drs.build_daily_report(db, t.id)
        assert len(report["phone_declines"]) == 1
        assert report["phone_declines"][0]["guest_id"] == guest.id

    def test_rendered_html_shows_guest_name_and_profile_link(self, db):
        t = _tenant(db)
        guest, conv, task = _declined_lead(db, t)
        report = drs.build_daily_report(db, t.id)
        html = render_daily_report(report, tenant_name=t.name, dashboard_url="https://app.example.com/dashboard")
        assert "Neil Moses" in html
        assert f"/guests/{guest.id}" in html
        assert "Declined to share a phone number" in html


class TestAgentReportPhoneDeclines:
    def test_agent_block_scopes_by_conversation_assignment(self, db):
        t = _tenant(db)
        agent = _agent(db, t.id)
        # Give the agent a scorecard row so build_agent_block doesn't
        # bail out early (returns None with no scorecard).
        from app.models.call import Call, CallDirection
        db.add(Call(
            tenant_id=t.id, agent_id=agent.id, direction=CallDirection.OUTBOUND,
            from_number="+910000000000", to_number="+910000000001",
            ivr_provider="vobiz", ivr_call_id=str(uuid.uuid4()),
            started_at=datetime.now(timezone.utc).isoformat(),
        ))
        db.commit()

        _declined_lead(db, t, assigned_to=agent.id, name="Assigned Lead")
        _declined_lead(db, t, assigned_to=None, name="Unassigned Lead")

        target = datetime.now(IST).date().isoformat()
        block = drs.build_agent_block(db, t.id, agent, target)
        assert block is not None
        names = [d["guest_name"] for d in block["phone_declines"]]
        assert names == ["Assigned Lead"]

    def test_rendered_agent_email_shows_the_section(self, db):
        t = _tenant(db)
        agent = _agent(db, t.id)
        from app.models.call import Call, CallDirection
        db.add(Call(
            tenant_id=t.id, agent_id=agent.id, direction=CallDirection.OUTBOUND,
            from_number="+910000000000", to_number="+910000000001",
            ivr_provider="vobiz", ivr_call_id=str(uuid.uuid4()),
            started_at=datetime.now(timezone.utc).isoformat(),
        ))
        db.commit()
        guest, conv, task = _declined_lead(db, t, assigned_to=agent.id, name="Assigned Lead")

        target = datetime.now(IST).date().isoformat()
        block = drs.build_agent_block(db, t.id, agent, target)
        block["date"] = target
        html = render_agent_report_html(block, tenant_name=t.name, dashboard_url="https://app.example.com/dashboard")
        assert "Assigned Lead" in html
        assert f"/guests/{guest.id}" in html


class TestAgentWorklistEmailPhoneDeclines:
    def test_rendered_html_includes_phone_declines_section(self):
        worklist = {
            "awaiting_reply": [],
            "overdue_followups": [],
            "phone_declines": [{"task_id": "t1", "conversation_id": "c1", "guest_id": "g1", "guest_name": "Neil Moses"}],
            "counts": {"awaiting_reply": 0, "overdue_followups": 0, "phone_declines": 1},
        }
        html = render_agent_worklist_html(
            worklist, agent_name="Krishna", tenant_name="Ratha",
            dashboard_url="https://app.example.com/dashboard", time_of_day="morning",
        )
        assert "Neil Moses" in html
        assert "Declined to share a phone number" in html
        assert "/guests/g1" in html
