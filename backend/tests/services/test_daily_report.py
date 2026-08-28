"""Daily owner report tests.

The failure this replaces is specific: the previous scheduled report built
every figure from an empty dict, so it emailed all-zero numbers under an
LLM-written narrative and logged success. These assert the report carries
real data and that the HTML is safe to put in an inbox.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

from app.models.call import Call, CallDirection, CallDisposition
from app.models.conversation import Conversation, Message, ChannelType, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource, LostReason
from app.models.insight import Insight
from app.models.pipeline_stage import PipelineStage
from app.models.property import Property, Stay
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


# ─── everything that happened that day ─────────────────────────────────────

def _property(db, t):
    p = Property(tenant_id=t.id, name="White Caravan", slug=f"wc-{uuid.uuid4().hex[:6]}")
    db.add(p); db.flush()
    return p


def test_bookings_and_revenue_use_when_the_booking_was_made(db):
    """Deliberately Stay.created_at, not Stay.check_in -- "what happened
    today" means bookings made today, not guests arriving today."""
    t = _tenant(db)
    p = _property(db, t)
    g = Guest(tenant_id=t.id, name="Ritik")
    db.add(g); db.flush()
    db.add(Stay(
        tenant_id=t.id, guest_id=g.id, property_id=p.id,
        check_in=date.today() + timedelta(days=30), check_out=date.today() + timedelta(days=31),
        status="confirmed", total_amount=42000, created_at=_yesterday_utc_noon(),
    ))
    db.commit()

    r = drs.build_daily_report(db, t.id)
    assert r["metrics"]["bookings"] == 1
    assert r["metrics"]["revenue"] == 42000.0


def test_cancelled_stays_are_excluded_from_bookings(db):
    t = _tenant(db)
    p = _property(db, t)
    g = Guest(tenant_id=t.id, name="Ritik")
    db.add(g); db.flush()
    db.add(Stay(
        tenant_id=t.id, guest_id=g.id, property_id=p.id,
        check_in=date.today(), check_out=date.today() + timedelta(days=1),
        status="cancelled", total_amount=42000, created_at=_yesterday_utc_noon(),
    ))
    db.commit()

    assert drs.build_daily_report(db, t.id)["metrics"]["bookings"] == 0


def test_lost_today_groups_by_reason(db):
    t = _tenant(db)
    lost_stage = PipelineStage(tenant_id=t.id, key="lost", label="Lost", is_closed_lost=True)
    db.add(lost_stage); db.flush()
    g = Guest(tenant_id=t.id, name="Deepa")
    db.add(g); db.flush()
    db.add(Inquiry(
        tenant_id=t.id, guest_id=g.id, source=InquirySource.PHONE, stage_id=lost_stage.id,
        lost_reason=LostReason.BUDGET_MISMATCH, quoted_amount=25000, route_mentioned="Bangalore to Coorg",
        current_stage_entered_at=_yesterday_utc_noon(),
    ))
    db.commit()

    r = drs.build_daily_report(db, t.id)
    assert r["lost_today"]["count"] == 1
    assert r["lost_today"]["reasons"] == [{"reason": "budget_mismatch", "count": 1}]
    assert r["lost_today"]["examples"][0]["guest_name"] == "Deepa"


def test_lost_today_excludes_leads_lost_on_other_days(db):
    t = _tenant(db)
    lost_stage = PipelineStage(tenant_id=t.id, key="lost", label="Lost", is_closed_lost=True)
    db.add(lost_stage); db.flush()
    g = Guest(tenant_id=t.id, name="Deepa")
    db.add(g); db.flush()
    db.add(Inquiry(
        tenant_id=t.id, guest_id=g.id, source=InquirySource.PHONE, stage_id=lost_stage.id,
        lost_reason=LostReason.BUDGET_MISMATCH,
        current_stage_entered_at=_yesterday_utc_noon() - timedelta(days=5),
    ))
    db.commit()

    assert drs.build_daily_report(db, t.id)["lost_today"]["count"] == 0


def test_calls_by_disposition_and_notable_calls(db):
    t = _tenant(db)
    db.add(Call(
        tenant_id=t.id, ivr_provider="vobiz", ivr_call_id=str(uuid.uuid4()),
        direction=CallDirection.INBOUND, from_number="+911111111111", to_number="+912222222222",
        human_disposition=CallDisposition.BOOKED, ai_score=95, ai_summary="Booked a caravan trip.",
        started_at=_yesterday_utc_noon().isoformat(), created_at=_yesterday_utc_noon(),
    ))
    db.add(Call(
        tenant_id=t.id, ivr_provider="vobiz", ivr_call_id=str(uuid.uuid4()),
        direction=CallDirection.INBOUND, from_number="+911111111112", to_number="+912222222222",
        ai_disposition=CallDisposition.LOST, ai_score=20, ai_summary="Guest declined the quote.",
        started_at=_yesterday_utc_noon().isoformat(), created_at=_yesterday_utc_noon(),
    ))
    db.commit()

    r = drs.build_daily_report(db, t.id)
    assert r["calls_by_disposition"] == {"booked": 1, "lost": 1}
    assert r["notable_calls"][0]["disposition"] == "booked"  # higher ai_score first
    assert "Booked" in r["notable_calls"][0]["summary"]


def test_tenant_isolation(db):
    t1, t2 = _tenant(db), _tenant(db)
    _conv_with_message(db, t1, MessageDirection.INBOUND)
    _conv_with_message(db, t2, MessageDirection.INBOUND)
    _conv_with_message(db, t2, MessageDirection.INBOUND)
    assert drs.build_daily_report(db, t1.id)["metrics"]["dms_in"] == 1


# ─── insights ────────────────────────────────────────────────────────────────

def _insight(db, t, severity, title, **kw):
    i = Insight(
        tenant_id=t.id, category_code=kw.get("category_code", "A1"), category="urgency",
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


def test_integration_degraded_insight_is_excluded(db):
    """D3 (integration health degraded) is suppressed from every surface
    this function feeds -- flagged as not wanted in the surfaced feed."""
    t = _tenant(db)
    _insight(db, t, "high", "Integrations degraded: vobiz, whatsapp_meta", category_code="D3")
    _insight(db, t, "high", "5 missed calls never called back", category_code="B2")
    out = drs.get_active_insights(db, t.id)
    assert [i["title"] for i in out] == ["5 missed calls never called back"]


# ─── email rendering ─────────────────────────────────────────────────────────

def _report_stub(**overrides):
    base = {
        "date": "2026-08-20",
        "metrics": {
            "dms_in": 3, "replies_out": 2, "by_channel": {"instagram": 3},
            "new_leads": 2, "qualified_leads": 0, "shared_details": 1,
            "calls_total": 0, "calls_missed": 0, "missed_not_returned": 0,
            "awaiting_reply": 206, "bookings": 0, "revenue": 0.0, "conversion_rate": 0.0,
        },
        "calls_by_disposition": {},
        "notable_calls": [],
        "lost_today": {"count": 0, "reasons": [], "examples": []},
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
