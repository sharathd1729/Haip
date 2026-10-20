"""The owner's daily brief (option C, owner pick 21 Oct 2026): owner_brief_service + owner_brief_email + the scheduled task.

Numbers come from the shared definitions (leads = people with a phone, booked value incl. add-ons, missed calls on the current
IVR provider only), compared with the 7 days before; sentences by rule; nothing sent on a quiet day; money only with
bookings.read; the off switch is respected; another workspace is never counted."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from app.models.call import Call, CallDirection
from app.models.guest import Guest
from app.models.property import Property, Stay
from app.models.stay_finance import StayAddOn
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import owner_brief_email, owner_brief_service
from app.services.date_presets import IST

NOW = datetime.now(IST).replace(hour=8, minute=0, second=0, microsecond=0)        # the morning brief's moment
YESTERDAY_NOON = (NOW - timedelta(days=1)).replace(hour=12).astimezone(timezone.utc)
APP = "https://app.example"


def _tenant(db, provider="vobiz"):
    t = Tenant(id=str(uuid.uuid4()), name="Ratha", slug=f"ob-{uuid.uuid4().hex[:6]}", plan="growth", ivr_provider=provider)
    db.add(t)
    db.commit()
    return t


def _lead(db, tid, when, name="Kiran"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name=name, phone=f"+9198{uuid.uuid4().int % 10**8:08d}",
              lead_identified_at=when, lead_identified_via="whatsapp")
    db.add(g)
    db.flush()
    return g


def _booking(db, tid, guest, amount, add_on=0, when=YESTERDAY_NOON):
    p = Property(id=str(uuid.uuid4()), tenant_id=tid, name="Ratha 1", slug=f"r-{uuid.uuid4().hex[:6]}")
    db.add(p)
    db.flush()
    s = Stay(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, property_id=p.id, status="confirmed",
             total_amount=amount, check_in=(NOW + timedelta(days=10)).date(), check_out=(NOW + timedelta(days=12)).date(),
             created_at=when)
    db.add(s)
    db.flush()
    if add_on:
        db.add(StayAddOn(tenant_id=tid, stay_id=s.id, name="Bonfire", quantity=1, unit_price=add_on))


def _missed(db, tid, provider, when=YESTERDAY_NOON):
    db.add(Call(id=str(uuid.uuid4()), tenant_id=tid, ivr_provider=provider, ivr_call_id=f"c-{uuid.uuid4().hex[:8]}",
                direction=CallDirection.INBOUND, from_number="+919800000000", to_number="+911", duration_seconds=0,
                ivr_dial_status="no-answer", created_at=when))


def _build(db, t, **kw):
    return owner_brief_service.build(db, t, kind="morning", app_url=APP, now=NOW, **kw)


def test_numbers_use_the_shared_definitions_and_compare_with_last_week(db):
    t, other = _tenant(db), _tenant(db)
    for i in range(3):
        _lead(db, t.id, YESTERDAY_NOON, name=f"Lead {i}")
    for d in range(2, 9):                                   # one lead a day in the week before: average 1
        _lead(db, t.id, YESTERDAY_NOON - timedelta(days=d - 1))
    g = _lead(db, t.id, YESTERDAY_NOON - timedelta(days=20))
    _booking(db, t.id, g, 100000, add_on=25000)
    _missed(db, t.id, "vobiz")
    _missed(db, t.id, "mcube")                              # a disconnected provider's history does not count
    _lead(db, other.id, YESTERDAY_NOON)                     # another workspace
    db.commit()

    b = _build(db, t)
    n = b["numbers"]
    assert (n["leads"], n["bookings"], n["booked_value"], n["missed_calls"]) == (3, 1, 125000, 1)
    text = " ".join(b["sentences"])
    assert "Yesterday brought 3 new leads (people who shared a phone number), more than your daily average of 1" in text
    assert "1 trip booked for ₹1,25,000." in text and "1 call went unanswered." in text
    assert b["worth_sending"] and b["my_day_url"] == f"{APP}/dashboard/my-day"


def test_money_is_left_out_for_readers_without_bookings_access(db):
    t = _tenant(db)
    _booking(db, t.id, _lead(db, t.id, YESTERDAY_NOON), 50000)
    db.commit()
    text = " ".join(_build(db, t, money=False)["sentences"])
    assert "1 trip booked." in text and "₹" not in text


def test_a_quiet_day_is_not_worth_an_email(db):
    t = _tenant(db)
    b = _build(db, t)
    assert b["worth_sending"] is False and b["sentences"] == ["No new leads yesterday."]


def test_people_to_call_now_become_the_todos_with_absolute_links(db):
    t = _tenant(db)
    _lead(db, t.id, datetime.now(timezone.utc) - timedelta(minutes=5), name="Ananya")       # fresh lead: Call now lane
    db.commit()
    todos = _build(db, t)["todos"]
    assert todos and todos[0]["text"].startswith("Call Ananya") and todos[0]["url"].startswith(APP + "/dashboard/")


def test_email_render_escapes_and_links(db):
    brief = {"kind": "morning", "period": "Yesterday", "day_label": "Tue, 20 Oct", "sentences": ["<b>3</b> leads."],
             "todos": [{"text": "Call A&B", "url": APP + "/dashboard/leads/1"}],
             "numbers": {"leads": 3, "bookings": 1}, "my_day_url": APP + "/dashboard/my-day", "dashboard_url": APP + "/dashboard"}
    html = owner_brief_email.html(brief, "Ratha <Caravans>")
    assert "&lt;b&gt;3&lt;/b&gt;" in html and "Call A&amp;B" in html and "Ratha &lt;Caravans&gt;" in html
    assert 'href="https://app.example/dashboard/my-day"' in html and 'name="viewport"' in html
    assert owner_brief_email.subject(brief, "Ratha") == "Ratha morning brief · Tue, 20 Oct: 3 new leads, 1 booked, 1 to call"
    assert "https://app.example/dashboard/leads/1" in owner_brief_email.text(brief, "Ratha")


def test_task_sends_to_owners_and_managers_who_kept_it_on(db):
    from app.workers.tasks import daily_owner_report as task
    from sqlalchemy.orm import Session as SASession
    t = _tenant(db)
    _lead(db, t.id, YESTERDAY_NOON)
    for role, email, prefs in ((UserRole.OWNER, "owner@x.com", {}), (UserRole.MANAGER, "off@x.com", {"morning_brief_email": False}),
                               (UserRole.CONCIERGE, "agent@x.com", {})):
        db.add(User(id=str(uuid.uuid4()), tenant_id=t.id, name="U", email=email, hashed_password="x", role=role,
                    is_active=True, notification_prefs=prefs))
    db.commit()
    assert [u.email for u in task.recipients(db, t.id)] == ["owner@x.com"]
    send = AsyncMock(return_value=True)
    with patch.object(task, "SessionLocal", lambda: SASession(bind=db.connection())), \
         patch("app.services.email_service._send", send), \
         patch("app.services.authz_service.has_capability", return_value=True):
        out = task.send_daily_owner_report.run(t.id, kind="morning")
    assert out["sent"] == 1 and send.call_args.args[0] == "owner@x.com"
    assert send.call_args.args[3]                                   # a plain-text part goes too


def test_task_skips_a_quiet_day(db):
    from app.workers.tasks import daily_owner_report as task
    from sqlalchemy.orm import Session as SASession
    t = _tenant(db)
    db.add(User(id=str(uuid.uuid4()), tenant_id=t.id, name="O", email="o@x.com", hashed_password="x", role=UserRole.OWNER,
                is_active=True))
    db.commit()
    send = AsyncMock(return_value=True)
    with patch.object(task, "SessionLocal", lambda: SASession(bind=db.connection())), \
         patch("app.services.email_service._send", send):
        out = task.send_daily_owner_report.run(t.id, kind="morning")
    assert out["status"] == "quiet_day" and send.call_count == 0
