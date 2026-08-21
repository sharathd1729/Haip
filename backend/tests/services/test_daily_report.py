"""Daily owner report tests.

The failure this replaces is specific: the previous scheduled report built
every figure from an empty dict, so it emailed all-zero numbers under an
LLM-written narrative and logged success. These assert the report carries
real data and that the HTML is safe to put in an inbox.
"""
import uuid
from datetime import datetime, timedelta, timezone

from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
from app.models.guest import Guest
from app.models.insight import Insight
from app.models.tenant import Tenant
from app.services import daily_report_service as drs
from app.services.daily_report_email import render_daily_report, render_subject
from app.services.date_presets import IST


def _tenant(db):
    t = Tenant(name="R", slug=f"r-{uuid.uuid4().hex[:8]}")
    db.add(t); db.commit()
    return t


def _yesterday_utc_noon() -> datetime:
    """Midday IST yesterday, expressed in UTC -- safely inside the window
    regardless of the +5:30 offset."""
    y = (datetime.now(IST) - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    return y.astimezone(timezone.utc)


def _conv_with_message(db, t, direction, *, body="hi", when=None):
    g = Guest(tenant_id=t.id, name="Arjun")
    db.add(g); db.flush()
    c = Conversation(tenant_id=t.id, guest_id=g.id, channel=ChannelType.INSTAGRAM, is_open=True)
    db.add(c); db.flush()
    m = Message(
        tenant_id=t.id, conversation_id=c.id, direction=direction,
        channel=ChannelType.INSTAGRAM, body=body,
        created_at=when or _yesterday_utc_noon(),
    )
    db.add(m); db.commit()
    return c, m


# ─── report data ─────────────────────────────────────────────────────────────

def test_counts_messages_in_the_ist_day(db):
    t = _tenant(db)
    _conv_with_message(db, t, MessageDirection.INBOUND)
    _conv_with_message(db, t, MessageDirection.INBOUND)
    _conv_with_message(db, t, MessageDirection.OUTBOUND)
    r = drs.build_daily_report(db, t.id)
    assert r["metrics"]["dms_in"] == 2
    assert r["metrics"]["replies_out"] == 1


def test_splits_inbound_by_channel(db):
    t = _tenant(db)
    _conv_with_message(db, t, MessageDirection.INBOUND)
    r = drs.build_daily_report(db, t.id)
    assert r["metrics"]["by_channel"].get("instagram") == 1


def test_messages_outside_the_day_are_excluded(db):
    t = _tenant(db)
    _conv_with_message(db, t, MessageDirection.INBOUND, when=_yesterday_utc_noon() - timedelta(days=4))
    assert drs.build_daily_report(db, t.id)["metrics"]["dms_in"] == 0


def test_morning_backlog_carries_over_recent_days(db):
    """The waiting figure is not limited to the reported day -- yesterday's
    unanswered leads still need chasing this morning."""
    t = _tenant(db)
    _conv_with_message(db, t, MessageDirection.INBOUND, when=_yesterday_utc_noon() - timedelta(days=2))
    r = drs.build_daily_report(db, t.id, kind=drs.KIND_MORNING)
    assert r["metrics"]["dms_in"] == 0          # not from the reported day
    assert r["metrics"]["awaiting_reply"] == 1  # but still outstanding


def test_morning_backlog_excludes_leads_older_than_the_window(db):
    """Ratha's all-time backlog is 200+, mostly dead Instagram reel replies.
    An owner cannot act on a fortnight-old one, so the window is bounded."""
    t = _tenant(db)
    _conv_with_message(
        db, t, MessageDirection.INBOUND,
        when=_yesterday_utc_noon() - timedelta(days=drs.BACKLOG_DAYS + 3),
    )
    r = drs.build_daily_report(db, t.id, kind=drs.KIND_MORNING)
    assert r["metrics"]["awaiting_reply"] == 0


def test_evening_counts_only_todays_unanswered(db):
    """The evening send is about salvaging today while it is still a
    reasonable hour to message someone."""
    t = _tenant(db)
    # Two days old -- outstanding, but not today's problem.
    _conv_with_message(db, t, MessageDirection.INBOUND, when=_yesterday_utc_noon() - timedelta(days=2))
    r = drs.build_daily_report(db, t.id, kind=drs.KIND_EVENING)
    assert r["metrics"]["awaiting_reply"] == 0


def test_evening_reports_today_not_yesterday(db):
    from app.services.date_presets import IST
    t = _tenant(db)
    r = drs.build_daily_report(db, t.id, kind=drs.KIND_EVENING)
    assert r["date"] == datetime.now(IST).date().isoformat()
    assert r["kind"] == drs.KIND_EVENING


def test_tenant_isolation(db):
    t1, t2 = _tenant(db), _tenant(db)
    _conv_with_message(db, t1, MessageDirection.INBOUND)
    _conv_with_message(db, t2, MessageDirection.INBOUND)
    _conv_with_message(db, t2, MessageDirection.INBOUND)
    assert drs.build_daily_report(db, t1.id)["metrics"]["dms_in"] == 1


# ─── insights ────────────────────────────────────────────────────────────────

def _insight(db, t, severity, title, **kw):
    i = Insight(
        tenant_id=t.id, category_code="A1", category="urgency",
        severity=severity, title=title,
        is_dismissed=kw.get("dismissed", False),
        is_auto_resolved=kw.get("resolved", False),
    )
    db.add(i); db.commit()
    return i


def test_insights_sorted_by_severity_before_limiting(db):
    """The existing inline copy of this query limits *then* sorts, so a
    critical insight outside the first N is silently dropped."""
    t = _tenant(db)
    for n in range(6):
        _insight(db, t, "low", f"low {n}")
    _insight(db, t, "critical", "THE CRITICAL ONE")
    out = drs.get_active_insights(db, t.id, limit=3)
    assert out[0]["title"] == "THE CRITICAL ONE"


def test_dismissed_and_resolved_insights_excluded(db):
    t = _tenant(db)
    _insight(db, t, "high", "dismissed", dismissed=True)
    _insight(db, t, "high", "resolved", resolved=True)
    _insight(db, t, "high", "live one")
    out = drs.get_active_insights(db, t.id)
    assert [i["title"] for i in out] == ["live one"]


# ─── email rendering ─────────────────────────────────────────────────────────

def _report_stub(**overrides):
    base = {
        "date": "2026-08-20",
        "metrics": {
            "dms_in": 3, "replies_out": 2, "by_channel": {"instagram": 3},
            "new_leads": 2, "qualified_leads": 0, "shared_details": 1,
            "calls_total": 0, "calls_missed": 0, "missed_not_returned": 0,
            "awaiting_reply": 206,
        },
        "top_waiting": [],
        "insights": [],
    }
    base.update(overrides)
    return base


def test_html_escapes_guest_names(db):
    """Guest names come from Instagram and WhatsApp -- fully attacker-controlled."""
    r = _report_stub(top_waiting=[{
        "name": '<script>alert(1)</script>',
        "channel": "instagram", "waiting_minutes": 90,
        "message": "<img src=x onerror=alert(2)>", "has_contact": False,
    }])
    html = render_daily_report(r, tenant_name="<b>T</b>", dashboard_url="https://x")
    # The property that matters is that no attacker-supplied *tag* survives:
    # "&lt;img src=x onerror=...&gt;" renders as visible text and cannot
    # execute, so the bare substring "onerror=" appearing inside escaped
    # text is harmless. Assert on the delimiters instead.
    assert "<script>" not in html
    assert "<img" not in html
    assert "<b>T</b>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;img" in html


def test_subject_leads_with_the_backlog(db):
    assert "206 waiting" in render_subject(_report_stub(), "Rathaa")


def test_subject_without_backlog_reports_volume(db):
    r = _report_stub()
    r["metrics"]["awaiting_reply"] = 0
    s = render_subject(r, "Rathaa")
    assert "waiting" not in s and "3 messages" in s


def test_all_clear_state_renders(db):
    r = _report_stub()
    r["metrics"].update(awaiting_reply=0, missed_not_returned=0)
    assert "Nothing outstanding" in render_daily_report(r, tenant_name="T", dashboard_url="https://x")


def test_missing_contact_details_is_flagged(db):
    r = _report_stub(top_waiting=[{
        "name": "Arjun", "channel": "instagram", "waiting_minutes": 30,
        "message": "hi", "has_contact": False,
    }])
    assert "No contact details captured" in render_daily_report(r, tenant_name="T", dashboard_url="https://x")
