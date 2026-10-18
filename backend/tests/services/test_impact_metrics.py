"""impact_metrics + impact_service: every number of the impact view against a small, fully known workspace.

Pinned: the guest-turn rule (24 h, multi-message turns, groups, internal notes, failed sends, too recent), the split per channel
(Cloud API / personal WhatsApp mirror / Instagram) and per responder (AI / staff with an AI draft / staff), after hours, the lead
cohort with quotes, missed calls returned, lost reasons, revenue per month, the windows and the change rule (no change against an
empty or zero baseline). Another workspace's and sample data never count. Runs on SQLite and PostgreSQL (no PG-only SQL).
"""
import uuid
from datetime import date, datetime, timezone

import pytest

from app.models.call import Call, CallDirection
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource, InquiryStage, LostReason
from app.models.inquiry_360 import InquiryQuote
from app.models.pipeline_stage import PipelineStage
from app.models.property import Property, Stay
from app.models.stay_finance import StayPayment
from app.models.tenant import Tenant
from app.services import impact_metrics as im
from app.services import impact_service as svc
from app.services.date_presets import ist_range_to_utc

NOW = datetime.fromisoformat("2026-09-30T18:00:00+05:30")
WITH = ist_range_to_utc("2026-09-01", "2026-09-30")[:2]
BEFORE = ist_range_to_utc("2026-08-02", "2026-08-31")[:2]


def _ist(s: str) -> datetime:
    return datetime.fromisoformat(f"{s}+05:30").astimezone(timezone.utc)


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="Ratha", slug=f"im-{uuid.uuid4().hex[:6]}", plan="growth", timezone="Asia/Kolkata")
    db.add(t); db.flush()
    return t


def _guest(db, tid, *, lead_at=None):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="G", phone=f"+9198{uuid.uuid4().int % 10**8:08d}", lead_identified_at=lead_at)
    db.add(g); db.flush()
    return g


def _conv(db, tid, channel=ChannelType.WHATSAPP, *, source=None, sample=False):
    g = _guest(db, tid)
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=channel, is_open=True, source=source, is_sample=sample)
    db.add(c); db.flush()
    return c


def _msg(db, c, when, direction="in", *, ai=False, auto=False, sender=None, state=None, internal=False, meta=None):
    m = Message(id=str(uuid.uuid4()), tenant_id=c.tenant_id, conversation_id=c.id, channel=c.channel, body="x",
                direction=MessageDirection.INBOUND if direction == "in" else MessageDirection.OUTBOUND, created_at=_ist(when),
                is_ai_generated=ai, sent_autonomously=auto, sender_id=sender, is_internal=internal, channel_metadata=meta,
                delivery_state=(state or (MessageDeliveryState.SENT if direction == "out" else None)), is_sample=c.is_sample)
    db.add(m); db.flush()
    return m


@pytest.fixture()
def chats(db):
    t = _tenant(db)
    staff = "staff-user"
    from app.models.user import User, UserRole
    db.add(User(id=staff, tenant_id=t.id, name="Asha", email=f"a-{uuid.uuid4().hex[:6]}@t.com", hashed_password="x",
                role=UserRole.CONCIERGE, is_active=True)); db.flush()
    pb = {"source": "personal_bridge", "chat_type": "user"}

    a = _conv(db, t.id)                                                     # WhatsApp Cloud API
    _msg(db, a, "2026-08-31T23:30:00")                                      # before window (after hours), answered 40 min later
    _msg(db, a, "2026-09-01T00:10:00", "out", sender=staff)
    _msg(db, a, "2026-09-10T10:00:00")
    _msg(db, a, "2026-09-10T10:01:00", "out", ai=True, auto=True)           # AI by itself: 60 s
    _msg(db, a, "2026-09-10T10:05:00")
    _msg(db, a, "2026-09-10T10:06:00")                                      # same turn
    _msg(db, a, "2026-09-10T10:20:00", "out", sender=staff)                 # staff: 900 s from 10:05
    _msg(db, a, "2026-09-10T23:00:00")                                      # after hours (Thu, closes 21:00)
    _msg(db, a, "2026-09-10T23:02:00", "out", ai=True, auto=True)           # AI: 120 s

    b = _conv(db, t.id, source="personal_bridge")                           # personal WhatsApp mirror
    _msg(db, b, "2026-09-10T11:00:00", meta=pb)
    _msg(db, b, "2026-09-10T11:30:00", "out", sender=staff, meta=pb)        # staff on own phone: 1800 s
    _msg(db, b, "2026-09-12T12:00:00", meta=pb)                             # never answered
    _msg(db, b, "2026-09-14T12:00:00", meta=pb)                             # > 24 h after a guest message: a new turn
    _msg(db, b, "2026-09-14T12:03:00", "out", sender=staff, meta=pb)        # 180 s
    g = _conv(db, t.id, source="personal_bridge")
    _msg(db, g, "2026-09-15T12:00:00", meta={"source": "personal_bridge", "chat_type": "group"})   # group: not a guest turn

    c = _conv(db, t.id, ChannelType.INSTAGRAM)
    _msg(db, c, "2026-09-11T09:30:00")
    _msg(db, c, "2026-09-11T09:31:00", "out", state=MessageDeliveryState.FAILED)   # failed send: not a reply
    _msg(db, c, "2026-09-11T09:32:00", "out", sender=staff, internal=True)          # internal note: not a reply
    _msg(db, c, "2026-09-11T10:30:00", "out", ai=True, sender=staff)                # staff sent an AI draft: 3600 s

    d = _conv(db, t.id)
    _msg(db, d, "2026-09-30T17:55:00")                                      # 5 minutes before NOW: too recent to judge
    s = _conv(db, t.id, sample=True)
    _msg(db, s, "2026-09-10T10:00:00")                                      # sample data never counts

    other = _tenant(db)
    o = _conv(db, other.id)
    _msg(db, o, "2026-09-10T10:00:00")
    db.commit()
    return t


def test_first_reply_all_channels(db, chats):
    r = im.first_replies(db, chats, *WITH, now=NOW)
    a = r["all"]
    assert (a["turns"], a["answered"], a["unanswered"]) == (7, 6, 1)
    assert a["median_seconds"] == 540.0               # 60 120 180 | 900 1800 3600
    assert a["p90_seconds"] == 2700.0
    assert a["within_pct"] == {"5": 42.9, "15": 57.1, "60": 85.7}   # of all 7 turns, unanswered included
    assert r["excluded_too_recent"] == 1 and r["truncated"] is False


def test_first_reply_by_channel(db, chats):
    ch = im.first_replies(db, chats, *WITH, now=NOW)["by_channel"]
    assert (ch["whatsapp_cloud"]["turns"], ch["whatsapp_cloud"]["median_seconds"]) == (3, 120.0)
    p = ch["personal_whatsapp"]
    assert (p["turns"], p["answered"], p["answered_pct"], p["median_seconds"]) == (3, 2, 66.7, 990.0)   # group chat excluded
    assert (ch["instagram"]["turns"], ch["instagram"]["median_seconds"]) == (1, 3600.0)


def test_first_reply_by_responder(db, chats):
    by = im.first_replies(db, chats, *WITH, now=NOW)["by_responder"]
    assert (by["ai"]["answered"], by["ai"]["median_seconds"], by["ai"]["within_15_pct"]) == (2, 90.0, 100.0)
    assert (by["staff"]["answered"], by["staff"]["median_seconds"]) == (3, 900.0)
    assert (by["staff_ai_draft"]["answered"], by["staff_ai_draft"]["median_seconds"]) == (1, 3600.0)


def test_after_hours_and_the_window_before(db, chats):
    ah = im.first_replies(db, chats, *WITH, now=NOW)["after_hours"]
    assert (ah["turns"], ah["answered"], ah["within_15_pct"], ah["answered_by_ai"], ah["ai_share_pct"]) == (1, 1, 100.0, 1, 100.0)
    before = im.first_replies(db, chats, *BEFORE, now=NOW)
    assert (before["all"]["turns"], before["all"]["median_seconds"]) == (1, 2400.0)
    assert before["after_hours"]["turns"] == 1 and before["after_hours"]["answered_by_ai"] == 0


def test_an_empty_period_has_no_statistic(db):
    t = _tenant(db); db.commit()
    r = im.first_replies(db, t, *WITH, now=NOW)
    assert r["all"]["turns"] == 0 and r["all"]["median_seconds"] is None and r["all"]["within_pct"]["15"] is None
    assert r["after_hours"]["ai_share_pct"] is None


def _stage(db, tid, key, *, lost=False):
    s = PipelineStage(id=str(uuid.uuid4()), tenant_id=tid, key=key, label=key, category="valid", order=1, is_closed_lost=lost)
    db.add(s); db.flush()
    return s


def _inquiry(db, tid, guest, stage, created, **kw):
    i = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, stage=InquiryStage.NEW, stage_id=stage.id,
                source=InquirySource.WA_DIRECT, created_at=_ist(created), **kw)
    db.add(i); db.flush()
    return i


@pytest.fixture()
def sales(db):
    t = _tenant(db)
    active, lost = _stage(db, t.id, "active"), _stage(db, t.id, "lost", lost=True)
    prop = Property(id=str(uuid.uuid4()), tenant_id=t.id, name="Ratha 1", slug=f"r-{uuid.uuid4().hex[:4]}", type="caravan", is_active=True)
    db.add(prop); db.flush()
    g1, g2, g3 = (_guest(db, t.id, lead_at=_ist(f"2026-09-0{d}T12:00:00")) for d in (2, 3, 4))
    i1 = _inquiry(db, t.id, g1, active, "2026-09-02T12:00:00")
    _inquiry(db, t.id, g2, active, "2026-09-03T12:00:00", quoted_at="2026-09-04T10:00:00")
    _inquiry(db, t.id, g3, active, "2026-09-04T12:00:00")
    _inquiry(db, t.id, g3, active, "2026-09-05T12:00:00", qualification_status="unqualified")     # spam enquiry: not counted
    db.add(InquiryQuote(id=str(uuid.uuid4()), tenant_id=t.id, inquiry_id=i1.id, amount=90000, status="issued"))
    stay = Stay(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g1.id, property_id=prop.id, check_in=date(2026, 11, 1),
                check_out=date(2026, 11, 3), status="confirmed", total_amount=50000, created_at=_ist("2026-08-20T12:00:00"))
    db.add(stay); db.flush()
    db.add(StayPayment(tenant_id=t.id, stay_id=stay.id, kind="payment", amount=20000, method="upi", paid_on=date(2026, 9, 5)))
    lg = _guest(db, t.id)
    _inquiry(db, t.id, lg, lost, "2026-08-01T12:00:00", lost_reason=LostReason.BUDGET_MISMATCH, current_stage_entered_at=_ist("2026-09-15T12:00:00"))
    _inquiry(db, t.id, lg, lost, "2026-08-01T12:00:00", current_stage_entered_at=_ist("2026-09-16T12:00:00"))
    _inquiry(db, t.id, lg, lost, "2026-08-01T12:00:00", lost_reason=LostReason.BUDGET_MISMATCH, current_stage_entered_at=_ist("2026-08-15T12:00:00"))

    def call(when, direction, duration, recovered=None):
        c = Call(id=str(uuid.uuid4()), tenant_id=t.id, ivr_provider="vobiz", ivr_call_id=uuid.uuid4().hex, direction=direction,
                 from_number="+919800000001", to_number="+918000000000", duration_seconds=duration, created_at=_ist(when),
                 recovered_by_call_id=recovered)
        db.add(c); db.flush()
        return c
    back = call("2026-09-10T10:20:00", CallDirection.OUTBOUND, 90)
    call("2026-09-10T10:00:00", CallDirection.INBOUND, 0, recovered=back.id)
    call("2026-09-11T10:00:00", CallDirection.INBOUND, 0)
    call("2026-09-12T10:00:00", CallDirection.INBOUND, 120)          # answered: not missed
    db.commit()
    return t


def test_funnel_is_a_cohort_with_quotes(db, sales):
    f = im.funnel(db, sales.id, *WITH)
    assert (f["enquiries"], f["leads"], f["quoted"], f["booked"]) == (3, 3, 2, 1)
    assert (f["lead_to_quote_pct"], f["lead_to_booking_pct"]) == (66.7, 33.3)


def test_missed_calls_returned_and_time_to_callback(db, sales):
    m = im.missed_calls(db, sales.id, *WITH)
    assert (m["missed"], m["returned"], m["returned_pct"], m["median_callback_seconds"], m["within_60_pct"]) == (2, 1, 50.0, 1200.0, 50.0)


def test_lost_enquiries_by_reason(db, sales):
    lost = im.lost_enquiries(db, sales.id, *WITH)
    assert lost["total"] == 2
    assert {i["reason"]: i["count"] for i in lost["by_reason"]} == {"budget_mismatch": 1, "not_recorded": 1}


def test_revenue_per_ist_month(db, sales):
    months = im.revenue_by_month(db, sales.id, date(2026, 8, 2), date(2026, 9, 30))
    assert [(m["month"], m["bookings"], m["booked_value"], m["collected"]) for m in months] == [
        ("2026-08", 1, 50000.0, 0.0), ("2026-09", 0, 0.0, 20000.0)]
    assert months[0]["from"] == "2026-08-01" and months[-1]["to"] == "2026-09-30"


def test_other_tenants_never_count(db, sales):
    other = _tenant(db); db.commit()
    assert im.funnel(db, other.id, *WITH)["leads"] == 0
    assert im.missed_calls(db, other.id, *WITH)["missed"] == 0
    assert im.lost_enquiries(db, other.id, *WITH)["total"] == 0


# ── windows and the change rule ──────────────────────────────────────────────────────────────────────────────

def test_windows_are_equal_and_never_start_before_go_live():
    w = svc.windows(date(2026, 9, 1), 30, today=date(2026, 9, 30))
    assert w["before"] == {"from": "2026-08-02", "to": "2026-08-31", "days": 30}
    assert w["with"] == {"from": "2026-09-01", "to": "2026-09-30", "days": 30}
    w = svc.windows(date(2026, 9, 25), 30, today=date(2026, 9, 30))
    assert w["with"]["from"] == "2026-09-25" and w["with"]["days"] == 6
    with pytest.raises(svc.ImpactError):
        svc.windows(date(2026, 10, 1), 30, today=date(2026, 9, 30))


def test_change_is_never_shown_against_an_empty_baseline():
    assert svc.change(None, 5, "minutes", True) is None
    assert svc.change(0, 5, "minutes", True) is None                    # never "-100%" or "+inf" against nothing
    assert svc.change(10, None, "minutes", True) is None
    assert svc.change(240, 9, "minutes", True) == {"kind": "pct", "value": -96.2, "better": True}
    assert svc.change(40, 70, "%", False) == {"kind": "points", "value": 30, "better": True}
    assert svc.change(40, 40, "%", False)["better"] is None


def test_percentile_matches_percentile_cont():
    assert im.percentile([], 0.5) is None
    assert im.percentile([10], 0.9) == 10
    assert im.percentile([1, 2, 3, 4], 0.5) == 2.5
