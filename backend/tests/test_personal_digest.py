"""Yaad's daily email (services/personal_digest.py + personal_digest_email.py, tasks personal.daily_digest*): only that
India-time day's calls of that workspace, still sent when the model fails, escaped, once a day, owners only,
personal workspaces only (and they no longer get the hotel owner brief)."""

import json
import uuid
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session as SASession

from app.models.user import User, UserRole
from app.services import personal_calls as pc
from app.services import personal_digest as svc
from app.services import personal_digest_email as email
from app.workers.tasks import personal_digest as task_mod
from tests.test_personal_calls import MEMORY, _personal
from tests.workers import call_analysis_harness as h

DAY = date(2026, 11, 14)
TODAY_IST_10AM = datetime(2026, 11, 14, 4, 30, tzinfo=UTC)
YESTERDAY = datetime(2026, 11, 13, 10, 0, tzinfo=UTC)
AI = {
    "glance": "The day centred on the delegation.",
    "decisions": ["Host the delegation", "host the delegation "],
    "learning": "Decide early.",
}


def _remembered(db, tenant_id, at, **memory):
    c = h.call(db, tenant_id, ivr_provider="mobile_app", with_transcript=False, created_at=at, duration_seconds=600)
    pc.store(c, pc.normalise({**MEMORY, **memory}))
    db.commit()
    return c


def _owner(db, tenant_id, role=UserRole.OWNER, name="Arjun Rao"):
    u = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id, email=f"{uuid.uuid4().hex[:6]}@example.com", name=name, role=role
    )
    db.add(u)
    db.commit()
    return u


def _workspace(db):
    t = h.tenant(db)
    _personal(db, t.id)
    return t


def test_build_reads_only_that_day_of_that_workspace(db):
    t = _workspace(db)
    _remembered(db, t.id, TODAY_IST_10AM)
    _remembered(db, t.id, YESTERDAY, open_points=["Yesterday's question"])
    _remembered(db, h.tenant(db).id, TODAY_IST_10AM, open_points=["Someone else's question"])
    llm = h.ScriptedLLM(tool_use=AI)
    with patch("app.services.personal_digest.get_llm", llm.get_llm):
        d = svc.build(db, t.id, DAY, "Arjun")
    assert d["glance"] == AI["glance"] and d["decisions"] == ["Host the delegation"]  # duplicates merged
    assert d["open_points"] == ["Who pays for travel?"] and d["learning"] == "Decide early."
    assert [(r["text"], r["owner"], r["due"]) for r in d["reminders"]] == [
        ("Book the venue", "Arjun", "2026-11-18"),
        ("Send visiting cards", "Prashant", ""),
    ]
    s = d["stats"]
    assert (s["calls"], s["reminders"], s["talk_minutes"], s["saved_minutes"]) == (1, 2, 10, 2)
    assert s["total_minutes"] == 20  # yesterday's call counts in the "so far" total, the other workspace does not
    assert "[1]" in llm.calls[0][1]["user_message"] and "Arjun" in llm.calls[0][1]["system_prompt"]


def test_model_failure_still_builds_the_lists(db):
    t = _workspace(db)
    _remembered(db, t.id, TODAY_IST_10AM)
    with patch("app.services.personal_digest.get_llm", h.ScriptedLLM(error=RuntimeError("down")).get_llm):
        d = svc.build(db, t.id, DAY, "Arjun")
    assert d["glance"] == "" and d["decisions"] == ["Host the delegation from 21 to 23 November."]
    assert d["learning"] == "Delegations decide on the first day." and len(d["reminders"]) == 2


def test_quiet_day_needs_no_model(db):
    t = _workspace(db)
    _remembered(db, t.id, YESTERDAY)
    with patch("app.services.personal_digest.get_llm", side_effect=AssertionError("no model call")):
        assert svc.build(db, t.id, DAY, "Arjun") is None


def test_email_escapes_everything_and_keeps_the_neo_sections():
    d = {
        "day": "2026-11-14",
        "owner_name": "Arjun",
        "glance": "<script>x</script>",
        "stats": {
            "calls": 1,
            "reminders": 1,
            "talk_minutes": 346,
            "saved_minutes": 86,
            "total_minutes": 35483,
            "total_saved_minutes": 8861,
        },
        "decisions": ["Pay <b>now</b>"],
        "reminders": [{"text": "Call & confirm", "owner": "Arjun", "due": "2026-11-21"}],
        "more_reminders": 0,
        "open_points": ["Who?"],
        "learning": "Be early.",
    }
    html = email.html(d, "https://app.example.com/")
    assert "<script>" not in html and "&lt;script&gt;" in html and "<b>now" not in html
    for heading in (
        "Your Day At A Glance",
        "Your Productivity Insights",
        "Decisions Taken Today",
        "Reminders From Today",
        "Open Points To Resolve",
        "Learning Of The Day",
    ):
        assert heading in html
    assert "21st Nov, 2026" in html and "https://app.example.com/dashboard/me/reminders" in html
    text = email.text(d, "https://app.example.com")
    assert "1. Call & confirm (Arjun, 21st Nov, 2026)" in text and "24 days 15 hrs 23 min recorded so far" in text
    assert email.subject(d) == "Your day, decoded: 1 call, 1 reminder · 14 Nov"


class _Cache:
    def __init__(self):
        self.data = {}

    def __enter__(self):
        self._p = [
            patch("app.core.cache.get_cached", side_effect=self.data.get),
            patch(
                "app.core.cache.set_cached",
                side_effect=lambda k, v, ttl=300: self.data.__setitem__(k, json.loads(json.dumps(v))),
            ),
        ]
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self._p:
            p.stop()


def _run(db, tenant_id, send):
    with (
        patch.object(task_mod, "SessionLocal", return_value=SASession(bind=db.connection())),
        patch("app.services.email_service._send", send),
        patch("app.services.personal_digest.get_llm", h.ScriptedLLM(tool_use=AI).get_llm),
    ):
        return task_mod.daily_digest.run(tenant_id, DAY.isoformat())


def test_task_emails_the_owner_once_a_day(db):
    t = _workspace(db)
    owner = _owner(db, t.id)
    _owner(db, t.id, role=UserRole.CONCIERGE)
    _remembered(db, t.id, TODAY_IST_10AM)
    send = AsyncMock(return_value=True)
    with _Cache():
        assert _run(db, t.id, send)["status"] == "sent"
        assert _run(db, t.id, send)["status"] == "already_sent"
    assert send.await_count == 1 and send.await_args.args[0] == owner.email
    assert send.await_args.args[1].startswith("Your day, decoded: 1 call")


def test_failed_send_retries_and_is_not_marked_sent(db):
    t = _workspace(db)
    _owner(db, t.id)
    _remembered(db, t.id, TODAY_IST_10AM)
    with _Cache() as c:
        with pytest.raises(Exception):  # noqa: B017 -- celery's Retry when the send failed
            _run(db, t.id, AsyncMock(return_value=False))
        assert not c.data


def test_business_workspace_and_quiet_day_send_nothing(db):
    business = h.tenant(db)
    _owner(db, business.id)
    send = AsyncMock(return_value=True)
    with _Cache():
        assert _run(db, business.id, send)["status"] == "not_personal"
        t = _workspace(db)
        _owner(db, t.id)
        assert _run(db, t.id, send)["status"] == "no_calls"
    send.assert_not_awaited()


def test_fan_out_queues_personal_workspaces_and_the_owner_brief_skips_them(db):
    from app.workers.tasks import daily_owner_report

    personal, business = _workspace(db), h.tenant(db)
    session = lambda: SASession(bind=db.connection())  # noqa: E731
    with (
        patch.object(task_mod.settings, "RESEND_API_KEY", "test"),
        patch.object(task_mod, "SessionLocal", side_effect=session),
        patch.object(daily_owner_report, "SessionLocal", side_effect=session),
        patch.object(task_mod.daily_digest, "delay") as digest,
        patch.object(daily_owner_report.send_daily_owner_report, "delay") as brief,
    ):
        task_mod.daily_digest_all_tenants()
        daily_owner_report.daily_owner_report_all_tenants()
    digested = {c.args[0] for c in digest.call_args_list}
    briefed = {c.args[0] for c in brief.call_args_list}
    assert personal.id in digested and business.id not in digested
    assert business.id in briefed and personal.id not in briefed
