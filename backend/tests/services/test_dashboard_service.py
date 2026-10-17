"""Owner Daily dashboard additions (dashboard_service): the four "Needs you
now" queues, per-day series and lead sources. Each queue must use the same
definition as the screen it links to, and an agent's numbers stay theirs."""
import uuid
from datetime import date, datetime, timedelta, timezone

from app.models.call import Call, CallDirection
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.property import Property, Stay
from app.models.task import Task
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import dashboard_service

NOW = datetime.now(timezone.utc)


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"d-{uuid.uuid4().hex[:6]}", plan="growth", ivr_provider="vobiz")
    db.add(t); db.flush(); return t


def _guest(db, tid):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="G", phone=f"+9197{uuid.uuid4().int % 10**8:08d}",
              lead_identified_at=NOW - timedelta(days=3))     # a lead: the number has been on file for days
    db.add(g); db.flush(); return g


def _user(db, tid):
    u = User(id=str(uuid.uuid4()), tenant_id=tid, name="Agent", email=f"a-{uuid.uuid4().hex[:6]}@t.com",
             role=UserRole.CONCIERGE, is_active=True)
    db.add(u); db.flush(); return u


def _waiting_conv(db, tid, assigned_to=None, minutes_ago=30):
    g = _guest(db, tid)
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=ChannelType.INSTAGRAM,
                     is_open=True, assigned_to=assigned_to)
    db.add(c); db.flush()
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=c.id, direction="inbound",
                   channel=ChannelType.INSTAGRAM, body="hi", created_at=NOW - timedelta(minutes=minutes_ago)))
    # A person already spoke to this lead on the phone, so only the unanswered message is outstanding (not a "new lead").
    db.add(Call(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, ivr_provider="vobiz", ivr_call_id=f"o-{uuid.uuid4().hex[:10]}",
                direction=CallDirection.OUTBOUND, from_number="+918000000000", to_number=g.phone, duration_seconds=90,
                ivr_dial_status="completed", created_at=NOW - timedelta(days=2)))
    db.flush()
    return c


def _missed_call(db, tid, days_ago=0, provider="vobiz"):
    g = _guest(db, tid)
    db.add(Call(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, ivr_provider=provider,
                ivr_call_id=f"c-{uuid.uuid4().hex[:10]}", direction=CallDirection.INBOUND,
                from_number=g.phone, to_number="+918000000000", duration_seconds=0,
                created_at=NOW - timedelta(days=days_ago, minutes=5)))
    db.flush()


def test_needs_you_now_counts_each_queue(db):
    t = _tenant(db)
    _waiting_conv(db, t.id)
    _waiting_conv(db, t.id, minutes_ago=60 * 24 * 9)          # past Meta's window -- not counted
    _missed_call(db, t.id)
    _missed_call(db, t.id, days_ago=10)                        # outside the callback window
    _missed_call(db, t.id, provider="mcube")                   # disconnected provider -- hidden
    db.add(Task(id=str(uuid.uuid4()), tenant_id=t.id, title="Call back", is_done=False,
                due_date=NOW - timedelta(hours=5), created_at=NOW - timedelta(days=30)))
    db.add(Task(id=str(uuid.uuid4()), tenant_id=t.id, title="Later", is_done=False, due_date=NOW + timedelta(days=1)))
    db.commit()

    got = dashboard_service.needs_you_now(db, t, scope_user_id=None)
    assert got["waiting_reply"] == 1 and got["waiting_oldest_at"]
    assert got["missed_not_called_back"] == 1 and got["missed_oldest_at"]
    # Overdue is by due date: a task created 30 days ago still counts.
    assert got["followups_overdue"] == 1


def test_needs_you_now_is_scoped_for_an_agent(db):
    t = _tenant(db)
    me, peer = _user(db, t.id), _user(db, t.id)
    _waiting_conv(db, t.id, assigned_to=me.id)
    _waiting_conv(db, t.id, assigned_to=peer.id)
    db.add(Task(id=str(uuid.uuid4()), tenant_id=t.id, title="x", is_done=False, assigned_to=peer.id,
                due_date=NOW - timedelta(hours=1)))
    db.commit()
    got = dashboard_service.needs_you_now(db, t, scope_user_id=me.id)
    assert got["waiting_reply"] == 1
    assert got["followups_overdue"] == 0


def test_daily_series_pads_single_day_and_buckets_revenue(db):
    t = _tenant(db)
    prop = Property(id=str(uuid.uuid4()), tenant_id=t.id, name="Caravan", slug=f"p-{uuid.uuid4().hex[:6]}")
    db.add(prop); db.flush()
    g = _guest(db, t.id)
    today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
    db.add(Stay(id=str(uuid.uuid4()), tenant_id=t.id, property_id=prop.id, guest_id=g.id,
                check_in=today, check_out=today + timedelta(days=2), status="confirmed", total_amount=42000))
    db.add(Inquiry(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, stage=InquiryStage.NEW,
                   source=InquirySource.META_IG, created_at=NOW - timedelta(minutes=10)))
    db.commit()

    s = dashboard_service.daily_series(db, t, None, today.isoformat(), today.isoformat())
    assert len(s["days"]) == 7 and s["days"][-1] == today.isoformat()
    assert s["revenue"][-1] == 42000 and s["bookings"][-1] == 1
    assert s["leads"][-1] == 1
    assert len(s["prev_revenue"]) == 7


def test_lead_sources_groups_channels(db):
    t = _tenant(db)
    g = _guest(db, t.id)
    for src in (InquirySource.META_IG, InquirySource.META_IG, InquirySource.WA_DIRECT, InquirySource.CLICK_TO_WA,
                InquirySource.INBOUND_CALL):
        db.add(Inquiry(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, stage=InquiryStage.NEW, source=src,
                       created_at=NOW - timedelta(hours=1)))
    db.commit()
    start = (NOW - timedelta(days=1)).isoformat()
    end = (NOW + timedelta(minutes=1)).isoformat()
    rows = {r["key"]: r for r in dashboard_service.lead_sources(db, t.id, None, start, end)}
    assert rows["instagram"]["count"] == 2
    assert rows["whatsapp"]["count"] == 2      # wa_direct + click_to_wa
    assert rows["call"]["count"] == 1
    assert rows["instagram"]["pct"] == 40


def test_other_tenants_are_invisible(db):
    a, b = _tenant(db), _tenant(db)
    _waiting_conv(db, b.id)
    _missed_call(db, b.id)
    db.commit()
    got = dashboard_service.needs_you_now(db, a, scope_user_id=None)
    assert got["waiting_reply"] == 0 and got["missed_not_called_back"] == 0
