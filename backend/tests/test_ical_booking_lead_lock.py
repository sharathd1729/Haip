"""Calendar bookings, part two: tying the booking to its lead (and marking it Sold), not double-booking a guest the CRM already
has, the lock that stops the calendar overwriting CRM edits, and the activity view on the settings page.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.security import create_access_token, get_password_hash
from app.models.guest import Guest
from app.models.ical_feed import ICalEventBooking
from app.models.inquiry import Inquiry
from app.models.pipeline_stage import PipelineStage
from app.models.property import Stay
from app.models.task import Task
from app.models.user import User, UserRole
from app.services import ical_booking_service as ibs
from tests.test_ical_calendar_bookings import _desc, _ev, _open_tasks, _stays
from tests.test_ical_feeds import _auth, _d
from tests.test_ical_shared_calendar import _event, _sync, shared  # noqa: F401  (shared is a fixture)

pytestmark = pytest.mark.usefixtures("capabilities_seeded")

PHONE = "+91 98000 11111"


def _stages(db, tid):
    rows = {}
    for key, order, kw in [("active", 1, {}), ("sold", 5, {"is_closed_won": True}), ("lost", 6, {"is_closed_lost": True})]:
        s = PipelineStage(id=str(uuid.uuid4()), tenant_id=tid, key=key, label=key.title(), order=order, category="valid", **kw)
        db.add(s)
        rows[key] = s
    db.commit()
    return rows


def _guest(db, tid, phone="+919800011111"):
    """The guest the calendar will resolve by phone (same number as the event)."""
    from app.services.identity_service import resolve_gid
    gid, _ = resolve_gid(db=db, tenant_id=tid, signal_type="phone", value=phone, source="test", guest_fields={"name": "Asha"})
    return gid


def _lead(db, tid, guest_id, stage, age_days=5, check_in=None):
    q = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest_id, stage_id=stage.id, check_in=check_in)
    db.add(q)
    db.flush()
    q.created_at = datetime.now(timezone.utc) - timedelta(days=age_days)
    db.commit()
    return q


def _stage_key(db, lead):
    db.refresh(lead)
    return db.query(PipelineStage).get(lead.stage_id).key


# ── lead link ────────────────────────────────────────────────────────────────

def test_the_booking_is_tied_to_the_guests_open_lead_and_the_lead_is_marked_sold(db, shared):
    st = _stages(db, shared["tid"])
    lead = _lead(db, shared["tid"], _guest(db, shared["tid"]), st["active"])
    _sync(db, shared["feed"], _ev())
    (stay,) = _stays(db, shared["tid"])
    assert stay.inquiry_id == lead.id and _stage_key(db, lead) == "sold"
    assert lead.check_in == _d(10)
    assert db.query(Stay).filter_by(inquiry_id=lead.id).count() == 1             # the Sold move did not add a second booking


def test_no_lead_means_a_plain_booking(db, shared):
    _stages(db, shared["tid"])
    _sync(db, shared["feed"], _ev())
    (stay,) = _stays(db, shared["tid"])
    assert stay.inquiry_id is None


def test_two_open_leads_are_not_guessed(db, shared):
    st = _stages(db, shared["tid"])
    gid = _guest(db, shared["tid"])
    a, b = _lead(db, shared["tid"], gid, st["active"]), _lead(db, shared["tid"], gid, st["active"])
    _sync(db, shared["feed"], _ev())
    (stay,) = _stays(db, shared["tid"])
    assert stay.inquiry_id is None and _stage_key(db, a) == _stage_key(db, b) == "active"
    assert len(_open_tasks(db, shared["tid"], ibs.LEAD_PREFIX)) == 1


def test_two_open_leads_are_told_apart_by_their_dates(db, shared):
    st = _stages(db, shared["tid"])
    gid = _guest(db, shared["tid"])
    _lead(db, shared["tid"], gid, st["active"], check_in=_d(200))
    near = _lead(db, shared["tid"], gid, st["active"], check_in=_d(11))
    _sync(db, shared["feed"], _ev())
    assert _stays(db, shared["tid"])[0].inquiry_id == near.id and _stage_key(db, near) == "sold"


@pytest.mark.parametrize("stage_key,age", [("lost", 5), ("sold", 5), ("active", 400)])
def test_lost_sold_or_stale_leads_are_left_alone(db, shared, stage_key, age):
    st = _stages(db, shared["tid"])
    lead = _lead(db, shared["tid"], _guest(db, shared["tid"]), st[stage_key], age_days=age)
    _sync(db, shared["feed"], _ev())
    assert _stays(db, shared["tid"])[0].inquiry_id is None and _stage_key(db, lead) == stage_key


def test_a_lead_that_already_has_a_booking_is_not_taken_again(db, shared):
    st = _stages(db, shared["tid"])
    gid = _guest(db, shared["tid"])
    lead = _lead(db, shared["tid"], gid, st["active"])
    db.add(Stay(tenant_id=shared["tid"], guest_id=gid, property_id=shared["black"].id, inquiry_id=lead.id,
                check_in=datetime(2031, 1, 1).date(), check_out=datetime(2031, 1, 3).date(), status="confirmed"))
    db.commit()
    _sync(db, shared["feed"], _ev())
    new = [s for s in _stays(db, shared["tid"]) if s.channel_source == "google_calendar"]
    assert len(new) == 1 and new[0].inquiry_id is None


def test_leads_of_other_guests_and_other_tenants_are_never_touched(db, shared):
    st = _stages(db, shared["tid"])
    someone = Guest(id=str(uuid.uuid4()), tenant_id=shared["tid"], name="Someone else")
    db.add(someone)
    db.flush()
    other = _lead(db, shared["tid"], someone.id, st["active"])
    _sync(db, shared["feed"], _ev())
    assert _stage_key(db, other) == "active"


# ── a guest the CRM already has ──────────────────────────────────────────────

def test_a_booking_already_in_the_crm_is_linked_not_duplicated(db, shared):
    gid = _guest(db, shared["tid"])
    mine = Stay(tenant_id=shared["tid"], guest_id=gid, property_id=shared["white"].id, status="confirmed",
                check_in=datetime.fromisoformat(_d(10)).date(), check_out=datetime.fromisoformat(_d(12)).date(), total_amount=25000)
    db.add(mine)
    db.commit()
    r = _sync(db, shared["feed"], _ev())
    assert r["bookings_created"] == 0 and r["bookings_linked"] == 1
    assert len(_stays(db, shared["tid"])) == 1
    link = db.query(ICalEventBooking).one()
    assert link.stay_id == mine.id and link.locked is True
    db.refresh(mine)
    assert float(mine.total_amount) == 25000.0                                       # the calendar's 30,000 did not overwrite it
    _sync(db, shared["feed"], _ev())
    assert len(_stays(db, shared["tid"])) == 1


# ── the lock ─────────────────────────────────────────────────────────────────

def test_editing_the_dates_or_total_in_the_crm_locks_the_booking_against_the_calendar(db, shared, client):
    _sync(db, shared["feed"], _ev())
    (stay,) = _stays(db, shared["tid"])
    h = _auth(shared["tu"])
    assert client.get(f"/api/v1/bookings/{stay.id}", headers=h).json()["calendar_sync"] == {"linked": True, "locked": False}
    r = client.patch(f"/api/v1/bookings/{stay.id}", json={"total_amount": 41000}, headers=h)
    assert r.status_code == 200, r.text
    assert client.get(f"/api/v1/bookings/{stay.id}", headers=h).json()["calendar_sync"]["locked"] is True
    _sync(db, shared["feed"], _event("b1@g", "Asha| Jishanth", _desc(total="Rs 99,000"), start=_d(10), end=_d(12)))
    db.refresh(stay)
    assert float(stay.total_amount) == 41000.0                                       # the CRM value stands


def test_picking_the_vehicle_or_a_note_does_not_lock(db, shared, client):
    _sync(db, shared["feed"], _ev())
    (stay,) = _stays(db, shared["tid"])
    h = _auth(shared["tu"])
    client.patch(f"/api/v1/bookings/{stay.id}", json={"property_id": shared["white"].id, "internal_notes": "pick-up at 9"}, headers=h)
    assert client.get(f"/api/v1/bookings/{stay.id}", headers=h).json()["calendar_sync"]["locked"] is False


def test_handing_it_back_to_the_calendar_makes_it_follow_again(db, shared, client):
    _sync(db, shared["feed"], _ev())
    (stay,) = _stays(db, shared["tid"])
    h = _auth(shared["tu"])
    client.patch(f"/api/v1/bookings/{stay.id}", json={"total_amount": 41000}, headers=h)
    r = client.put(f"/api/v1/bookings/{stay.id}/calendar-sync", json={"locked": False}, headers=h)
    assert r.status_code == 200 and r.json()["calendar_sync"]["locked"] is False
    _sync(db, shared["feed"], _event("b1@g", "Asha| Jishanth", _desc(total="Rs 99,000"), start=_d(10), end=_d(12)))
    db.refresh(stay)
    assert float(stay.total_amount) == 99000.0


def test_a_locked_booking_is_not_cancelled_when_the_event_disappears_but_a_task_says_so(db, shared, client):
    _sync(db, shared["feed"], _ev())
    (stay,) = _stays(db, shared["tid"])
    client.patch(f"/api/v1/bookings/{stay.id}", json={"adults": 6}, headers=_auth(shared["tu"]))
    r = _sync(db, shared["feed"])
    db.refresh(stay)
    assert r["bookings_cancelled"] == 0 and stay.status == "confirmed"
    assert len(_open_tasks(db, shared["tid"], "Calendar event was deleted")) == 1


def test_the_lock_endpoint_is_for_calendar_bookings_and_managers_only(db, shared, client):
    h = _auth(shared["tu"])
    plain = Stay(tenant_id=shared["tid"], guest_id=_guest(db, shared["tid"]), property_id=shared["white"].id, status="confirmed",
                 check_in=datetime(2031, 5, 1).date(), check_out=datetime(2031, 5, 3).date())
    db.add(plain)
    db.commit()
    assert client.put(f"/api/v1/bookings/{plain.id}/calendar-sync", json={"locked": True}, headers=h).status_code == 404
    _sync(db, shared["feed"], _ev())
    cal = next(s for s in _stays(db, shared["tid"]) if s.channel_source == "google_calendar")
    foh = User(id=str(uuid.uuid4()), tenant_id=shared["tid"], name="F", email=f"f-{uuid.uuid4().hex[:5]}@t.com",
               hashed_password=get_password_hash("pw"), role=UserRole.FOH, is_active=True)
    db.add(foh)
    db.commit()
    hf = {"Authorization": "Bearer " + create_access_token({"sub": foh.id, "tenant_id": shared["tid"], "role": "foh"})}
    assert client.put(f"/api/v1/bookings/{cal.id}/calendar-sync", json={"locked": True}, headers=hf).status_code == 403


# ── activity view ────────────────────────────────────────────────────────────

def test_the_activity_view_lists_bookings_and_why_other_events_were_not_booked(db, shared, client):
    _sync(db, shared["feed"], _ev(), _event("x@g", "Ravi| Jishanth", _desc(phone=None), start=_d(20), end=_d(23)))
    out = client.get(f"/api/v1/ical-feeds/{shared['feed'].id}/activity", headers=_auth(shared["tu"])).json()
    (b,) = out["bookings"]
    assert b["guest_name"] and b["vehicle"] == "Ratha Black" and b["locked"] is False and b["status"] == "confirmed"
    (s,) = out["skipped"]
    assert s["title"] == "Ravi| Jishanth" and s["reasons"] == ["no phone number"]
    assert "98000" not in str(out) and "30000" not in str(out)                        # no phone, no money


def test_the_activity_view_is_tenant_scoped(db, shared, client):
    _sync(db, shared["feed"], _ev())
    other = _tenant_owner(db)
    r = client.get(f"/api/v1/ical-feeds/{shared['feed'].id}/activity", headers=other)
    assert r.status_code == 404


def _tenant_owner(db):
    from tests.test_ical_feeds import _tenant
    from tests.conftest import seed_capabilities
    tid = _tenant(db)
    seed_capabilities(db, tid)
    u = User(id=str(uuid.uuid4()), tenant_id=tid, name="O", email=f"o-{uuid.uuid4().hex[:5]}@t.com",
             hashed_password=get_password_hash("pw"), role=UserRole.OWNER, is_active=True)
    db.add(u)
    db.commit()
    return {"Authorization": "Bearer " + create_access_token({"sub": u.id, "tenant_id": tid, "role": "owner"})}
