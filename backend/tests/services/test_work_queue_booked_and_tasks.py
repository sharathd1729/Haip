"""My day fixes (19 Oct 2026): booked people are guests, not leads to chase; follow-ups only about leads (or nobody); and the
calendar sync's own tasks are the separate ``clash`` kind.

Real cases behind these: "Krithika (Brandaid Events)" -- created by a staff manual booking, no enquiry, three confirmed stays --
sat under new_lead ("Shared their number", then "Gone cold"); "Call lead about pricing -- Priyanka" for an Instagram guest
with no phone sat under Follow-ups; stale "Double booking on Unassigned (legacy ...)" tasks sat under Follow-ups.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

from app.models.base import gen_uuid
from app.models.call import Call, CallDirection
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.property import Property, Stay
from app.models.task import Task
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import dashboard_service, work_queue_service as wq, work_queue_signals
from app.services.date_presets import IST

NOW = datetime.now(timezone.utc)
TODAY = datetime.now(IST).date()


def _tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"wqb-{uuid.uuid4().hex[:6]}", plan="growth", ivr_provider="vobiz")
    db.add(t); db.flush(); return t


def _user(db, tid):
    u = User(id=str(uuid.uuid4()), tenant_id=tid, name="Agent", email=f"a-{uuid.uuid4().hex[:6]}@t.com",
             role=UserRole.CONCIERGE, is_active=True)
    db.add(u); db.flush(); return u


def _guest(db, tid, name, days_ago=11, phone=True):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name=name,
              phone=f"+9198{uuid.uuid4().int % 10**8:08d}" if phone else "",
              lead_identified_via="other" if phone else None,
              lead_identified_at=(NOW - timedelta(days=days_ago)) if phone else None)
    db.add(g); db.flush(); return g


def _prop(db, tid, name="Ratha 1"):
    p = Property(id=gen_uuid(), tenant_id=tid, name=name, slug=f"p-{uuid.uuid4().hex[:6]}", type="caravan", is_active=True)
    db.add(p); db.flush(); return p


def _stay(db, tid, guest, prop, check_in, nights=2, status="confirmed", created=None):
    s = Stay(id=gen_uuid(), tenant_id=tid, guest_id=guest.id, property_id=prop.id, check_in=check_in,
             check_out=check_in + timedelta(days=nights), status=status, created_at=created or NOW - timedelta(days=11) + timedelta(minutes=1))
    db.add(s); db.flush(); return s


def _conv(db, tid, guest, channel=ChannelType.WHATSAPP):
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, channel=channel, is_open=True)
    db.add(c); db.flush(); return c


def _msg(db, tid, conv, direction, minutes_ago, body="hello?", **kw):
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=direction, channel=conv.channel,
                   body=body, created_at=NOW - timedelta(minutes=minutes_ago), **kw))
    db.flush()


def _krithika(db, tid, name="Krithika (Brandaid Events)", status="confirmed"):
    """A guest made by a staff manual booking: number on file, no enquiry, booked."""
    g = _guest(db, tid, name)
    p = _prop(db, tid)
    _stay(db, tid, g, p, TODAY - timedelta(days=7), status=status)
    _stay(db, tid, g, p, TODAY - timedelta(days=4), nights=1, status=status)
    return g


def _by_title(res):
    return {i["title"]: i for i in res["items"]}


# ── booked people (bug 1) ────────────────────────────────────────────────────

def test_a_booked_guest_with_no_enquiry_is_not_a_lead_to_chase(db):
    t, other = _tenant(db), _tenant(db)
    _krithika(db, t.id)
    _guest(db, t.id, "Real lead", days_ago=1)
    db.commit()

    res = wq.build(db, t, scope_user_id=None)
    assert set(_by_title(res)) == {"Real lead"}
    assert res["counts"]["new_lead"] == 1 and res["flags"]["not_called"] == 1
    cards = dashboard_service.needs_you_now(db, t, scope_user_id=None)
    assert cards["new_leads"] == 1
    assert wq.build(db, other, scope_user_id=None)["total"] == 0


def test_a_booked_guest_who_writes_and_gets_no_answer_is_still_a_reply_without_lead_flags(db):
    t = _tenant(db)
    g = _krithika(db, t.id)
    c = _conv(db, t.id, g)
    _msg(db, t.id, c, "inbound", 60, body="What time is check-in tomorrow?")
    db.commit()

    res = wq.build(db, t, scope_user_id=None)
    item = _by_title(res)["Krithika (Brandaid Events)"]
    assert item["kind"] == "reply" and "check-in" in item["detail"]
    assert item["flags"] == [] and res["flags"]["not_called"] == 0


def test_a_booked_guest_is_never_not_replying(db):
    t = _tenant(db)
    g = _krithika(db, t.id)
    c = _conv(db, t.id, g)
    _msg(db, t.id, c, "outbound", 60 * 30, body="Your booking is confirmed", is_internal=False)
    db.commit()
    res = wq.build(db, t, scope_user_id=None)
    assert res["counts"]["no_reply"] == 0 and res["total"] == 0


def test_a_cancelled_booking_does_not_hide_the_lead(db):
    t = _tenant(db)
    _krithika(db, t.id, name="Cancelled", status="cancelled")
    db.commit()
    res = wq.build(db, t, scope_user_id=None)
    assert _by_title(res)["Cancelled"]["kind"] == "new_lead"
    assert "not_called" in _by_title(res)["Cancelled"]["flags"]


def test_an_old_stay_from_before_they_became_a_lead_does_not_count_but_an_upcoming_one_does(db):
    t = _tenant(db)
    p = _prop(db, t.id)
    old = _guest(db, t.id, "Stayed long ago", days_ago=3)
    _stay(db, t.id, old, p, TODAY - timedelta(days=200), created=NOW - timedelta(days=220))
    coming = _guest(db, t.id, "Coming soon", days_ago=3)
    _stay(db, t.id, coming, p, TODAY + timedelta(days=10), created=NOW - timedelta(days=30))
    db.commit()
    assert set(_by_title(wq.build(db, t, scope_user_id=None))) == {"Stayed long ago"}


def test_a_newer_open_enquiry_makes_a_past_guest_a_lead_again(db):
    t = _tenant(db)
    g = _krithika(db, t.id, name="Back again")
    db.add(Inquiry(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, stage=InquiryStage.NEW, source=InquirySource.WA_DIRECT,
                   created_at=NOW - timedelta(days=1)))
    db.commit()
    assert _by_title(wq.build(db, t, scope_user_id=None))["Back again"]["kind"] == "new_lead"


def test_booked_guests_reads_only_its_own_workspace(db):
    t, other = _tenant(db), _tenant(db)
    g = _guest(db, t.id, "Mine")
    p = _prop(db, other.id)
    # A stay row under ANOTHER workspace (as if a bad link pointed at this guest) must not mark them booked here.
    db.add(Stay(id=gen_uuid(), tenant_id=other.id, guest_id=g.id, property_id=p.id, check_in=TODAY, check_out=TODAY + timedelta(days=1),
                status="confirmed"))
    db.flush()
    assert work_queue_signals.booked_guests(db, t.id, [g.id], TODAY) == set()
    assert work_queue_signals.booked_guests(db, other.id, [g.id], TODAY) == {g.id}


# ── follow-ups only about leads (bug 2) ──────────────────────────────────────

def _task(db, tid, title, **kw):
    t = Task(id=str(uuid.uuid4()), tenant_id=tid, title=title, is_done=False, due_date=NOW - timedelta(hours=2), **kw)
    db.add(t); db.flush(); return t


def test_follow_ups_list_lead_tasks_and_manual_tasks_but_not_tasks_about_a_guest_with_no_phone(db):
    t, other = _tenant(db), _tenant(db)
    me = _user(db, t.id)
    priyanka = _guest(db, t.id, "Priyanka", phone=False)
    ig = _conv(db, t.id, priyanka, ChannelType.INSTAGRAM)
    lead = _guest(db, t.id, "Asha", days_ago=2)
    lead_conv = _conv(db, t.id, lead)
    no_phone_inq = Inquiry(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=priyanka.id, stage=InquiryStage.NEW,
                           source=InquirySource.META_IG)
    db.add(no_phone_inq); db.flush()
    _task(db, t.id, "Call lead about pricing — Priyanka", guest_id=priyanka.id, conversation_id=ig.id)
    _task(db, t.id, "Send the quote yourself: Priyanka", inquiry_id=no_phone_inq.id)          # guest found via the enquiry
    _task(db, t.id, "Guest declined phone number — Priyanka", conversation_id=ig.id)            # guest found via the chat
    _task(db, t.id, "Call lead about pricing — Asha", guest_id=lead.id, conversation_id=lead_conv.id)
    _task(db, t.id, "Order a new gas cylinder", created_by=me.id)
    _task(db, other.id, "Other workspace task", created_by=None)
    db.commit()

    res = wq.build(db, t, scope_user_id=None)
    assert {i["title"] for i in res["items"] if i["kind"] == "followup"} == {
        "Call lead about pricing — Asha", "Order a new gas cylinder"}
    assert res["counts"]["followup"] == 2


# ── calendar clashes (bug 3) ─────────────────────────────────────────────────

def test_calendar_tasks_are_their_own_kind_not_follow_ups(db):
    t, other = _tenant(db), _tenant(db)
    p = _prop(db, t.id, "Ratha 2")
    booked = _krithika(db, t.id, name="Booked")
    start = (TODAY + timedelta(days=1)).isoformat()
    end = (TODAY + timedelta(days=2)).isoformat()
    _task(db, t.id, f"Double booking on Ratha 2: Google {start} to {end}", guest_id=booked.id, priority="high")
    _task(db, t.id, f"Which vehicle? Trip to Coorg ({start} to {end})")
    _task(db, other.id, f"Double booking on Ratha 2: Google {start} to {end}")
    db.commit()

    res = wq.build(db, t, scope_user_id=None)
    clashes = [i for i in res["items"] if i["kind"] == "clash"]
    assert len(clashes) == 2 and res["counts"]["clash"] == 2 and res["counts"]["followup"] == 0
    dbl = next(i for i in clashes if i["title"].startswith("Double booking"))
    assert dbl["href"] == f"/dashboard/portfolio/calendar?date={start}&property={p.id}"
    assert "Ratha 2" in dbl["facts"] and dbl["severity"] == "critical" and dbl["guest_id"] is None
    # The nav badge total includes clashes (they need action); "people" and the dashboard follow-up card do not.
    assert res["total"] == 2 and res["people"] == 0
    cards = dashboard_service.needs_you_now(db, t, scope_user_id=None)
    assert cards["followups_overdue"] == 0 and cards["people"] == 0
    assert res["severity"]["critical"] == 0      # severity counts are people's SLAs
