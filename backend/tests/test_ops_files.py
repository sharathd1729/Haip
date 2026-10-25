"""Ops files, caravan pack (migration 179): the Ratha prototype's workflow, gate and money tests, ported.

The money test reproduces the real Saleem trip (Aug 2026): 84 h / 1,200 km package Rs 1,26,732 incl. GST, odometer
87,396 -> 88,792 (196 km over at Rs 65 incl. GST = Rs 12,740), expenses Rs 27,670.60. Total Rs 1,39,472.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.models.audit_event import AuditEvent
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.inquiry_360 import InquiryQuote
from app.models.ops_files import OpsFile, OpsJobItem
from app.models.property import Stay
from app.models.stay_finance import StayAddOn, StayDeposit, StayPayment
from app.models.user import User, UserRole
from app.schemas.ops_files import AcceptIn, CrewIn, ExpenseIn, ExtraIn
from app.services import ops_money as money
from app.services import ops_trip_service as trips
from tests.conftest import seed_capabilities
from tests.ops_helpers import prop, staff, tenant
from tests.test_increment1_defect_specs import _h, _user

TODAY = date.today()


def _tenant(db, business_type="caravan"):
    t = tenant(db)
    t.business_type = business_type
    db.commit()
    return t


def _stay(db, t, p, *, start=3, nights=3, total="126732", status="confirmed", inquiry_id=None) -> Stay:
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Sample Guest", phone=f"+9199{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    s = Stay(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, property_id=p.id, check_in=TODAY + timedelta(days=start),
             check_out=TODAY + timedelta(days=start + nights), adults=6, children=2, status=status,
             total_amount=Decimal(total), inquiry_id=inquiry_id)
    db.add(s)
    db.commit()
    return s


def _pay(db, stay, amount):
    db.add(StayPayment(tenant_id=stay.tenant_id, stay_id=stay.id, amount=Decimal(amount), method="upi", paid_on=TODAY))
    db.flush()


@pytest.fixture(autouse=True)
def _actor_u1(db):
    """Service calls here act as user "u1". PostgreSQL checks audit actors against users (SQLite does not), so it exists."""
    if db.get(User, "u1") is None:
        t = tenant(db)
        db.add(User(id="u1", tenant_id=t.id, name="Manager", email=f"u1-{uuid.uuid4().hex[:6]}@t.com", hashed_password="x",
                    role=UserRole.MANAGER, is_active=True))
        db.commit()


@pytest.fixture()
def w(db):
    t = _tenant(db)
    p = prop(db, t.id, "Ratha 1")
    return type("W", (), {"t": t, "p": p, "stay": _stay(db, t, p), "driver": staff(db, t.id, "Suresh", "driver"),
                          "helper": staff(db, t.id, "Raju", "driver")})()


def _green_all_critical(db, f):
    for i in trips.readiness_items(db, f):
        if i.critical and i.source != "system":
            trips.set_item(db, f, i.key, "green", None, user_id="u1")


def _ready_file(db, w, allowance="1200", rate="65", incl=True):
    f = trips.ensure_file(db, w.t.id, w.stay)
    trips.accept(db, f, AcceptIn(route="Bangalore -> Hyderabad", stops=["Bangalore", "Kurnool", "Hyderabad"],
                                 allowance_km=Decimal(allowance), extra_km_rate=Decimal(rate), rate_includes_gst=incl), "u1")
    trips.set_crew(db, f, CrewIn(driver_staff_id=w.driver.id, helper_staff_id=w.helper.id), "u1")
    return f


def test_file_is_created_once_with_the_12_point_gate(db, w):
    f = trips.ensure_file(db, w.t.id, w.stay)
    assert f.state == "handed_over" and f.pack == "caravan_rv"
    items = trips.readiness_items(db, f)
    assert len(items) == 12 and sum(i.critical for i in items) == 9
    assert trips.ensure_file(db, w.t.id, w.stay).id == f.id
    assert db.query(OpsFile).filter_by(stay_id=w.stay.id).count() == 1


def test_no_file_without_a_pack_or_for_a_cancelled_booking(db):
    t = _tenant(db, "hotel")
    p = prop(db, t.id, "Room 1")
    assert trips.ensure_file(db, t.id, _stay(db, t, p)) is None
    t2 = _tenant(db)
    p2 = prop(db, t2.id)
    assert trips.ensure_file(db, t2.id, _stay(db, t2, p2, status="cancelled")) is None


def test_km_included_and_rate_come_from_the_booking_quote(db, w):
    g = Guest(id=str(uuid.uuid4()), tenant_id=w.t.id, name="Quoted Guest", phone="+919900011122")
    db.add(g)
    db.flush()
    inq = str(uuid.uuid4())
    db.add(Inquiry(id=inq, tenant_id=w.t.id, guest_id=g.id, source=InquirySource.WA_DIRECT, stage=InquiryStage.NEW))
    db.flush()
    db.add(InquiryQuote(tenant_id=w.t.id, inquiry_id=inq, amount=Decimal("126732"), status="accepted", option_rank=1,
                        snapshot={"gst_percent": "18", "km": {"included_km": "700", "applied_rate": "60"}}))
    stay = _stay(db, w.t, w.p, start=20, inquiry_id=inq)
    d = money.details(trips.ensure_file(db, w.t.id, stay))
    assert (d.allowance_km, d.extra_km_rate, d.rate_includes_gst, d.rate_source) == (Decimal("700"), Decimal("60"), False, "quote_km")


def test_accept_needs_km_included_when_no_quote_has_it(db, w):
    f = trips.ensure_file(db, w.t.id, w.stay)
    with pytest.raises(HTTPException) as e:
        trips.accept(db, f, AcceptIn(route="Coorg"), "u1")
    assert e.value.status_code == 422


def test_gate_blocks_dispatch_until_every_critical_check_is_green(db, w):
    f = _ready_file(db, w)
    assert f.state == "readiness"
    with pytest.raises(HTTPException):
        trips.dispatch(db, f, 87396, "u1")
    _green_all_critical(db, f)
    assert f.state == "readiness"                       # payment (system) still pending: nothing paid yet
    _pay(db, w.stay, "126732")
    trips.refresh(db, f)
    assert f.state == "dispatch_ready"
    trips.set_item(db, f, "ac", "red", "AC not cooling", user_id="u1")
    assert f.state == "readiness"
    trips.set_item(db, f, "ac", "green", None, user_id="u1")
    trips.dispatch(db, f, 87396, "u1")
    assert f.state == "on_trip" and money.details(f).start_odometer == 87396
    db.flush()
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="ops.trip.dispatched").count() == 1
    with pytest.raises(HTTPException):
        trips.set_item(db, f, "ac", "red", None, user_id="u1")


def test_a_held_deposit_is_needed_for_the_payment_check(db, w):
    f = _ready_file(db, w)
    _green_all_critical(db, f)
    _pay(db, w.stay, "126732")
    db.add(StayDeposit(tenant_id=w.t.id, stay_id=w.stay.id, amount=Decimal("10000"), status="pending"))
    db.flush()
    trips.refresh(db, f)
    assert f.state == "readiness"
    db.query(StayDeposit).filter_by(stay_id=w.stay.id).update({"status": "held"})
    trips.refresh(db, f)
    assert f.state == "dispatch_ready"


def test_saleem_trip_account_and_close(db, w):
    f = _ready_file(db, w)
    _green_all_critical(db, f)
    _pay(db, w.stay, "126732")
    trips.refresh(db, f)
    trips.dispatch(db, f, 87396, "u1")
    with pytest.raises(HTTPException):
        trips.end_trip(db, f, 87000)
    for cat, amt in (("driver", "8750"), ("helper", "1300"), ("fuel", "17620.60")):
        money.add_expense(db, f, ExpenseIn(category=cat, amount=Decimal(amt)), actor_id="u1")
    trips.end_trip(db, f, 88792, actor_id="u1")
    a = money.account(db, f)
    assert (a["distance_km"], a["extra_km"], a["extra_km_charge"]) == (1396, 196, Decimal("12740.00"))
    assert a["total_revenue"] == Decimal("139472.00") and a["total_expenses"] == Decimal("27670.60")
    assert a["net_cash"] == Decimal("111801.40") and a["outstanding"] == Decimal("12740.00")
    addon = db.query(StayAddOn).filter_by(stay_id=w.stay.id, name=money.EXTRA_KM_ADDON).one()
    assert addon.unit_price == Decimal("12740.00") and "196 km" in addon.notes
    money.post_extra_km(db, f)                          # idempotent
    assert db.query(StayAddOn).filter_by(stay_id=w.stay.id).count() == 1

    with pytest.raises(HTTPException) as e:
        trips.close(db, f, "u1")
    assert "balance" in e.value.detail and "report" in e.value.detail and "checked on return" in e.value.detail
    trips.settle(db, f, "return_checked", "u1")
    trips.settle(db, f, "report_approved", "u1")
    _pay(db, w.stay, "12740")
    trips.close(db, f, "u1")
    assert f.state == "closed" and trips.stage(db, f)["next"] == ""


def test_extra_km_rate_before_gst_adds_gst(db, w):
    f = _ready_file(db, w, allowance="700", rate="60", incl=False)
    d = money.details(f)
    d.start_odometer, d.end_odometer = 1000, 1800
    assert money.extra_km_charge(d, Decimal("18")) == Decimal("7080.00")       # 100 km x 60 x 1.18


def test_crew_cannot_be_on_two_overlapping_trips(db, w):
    _ready_file(db, w)
    other_vehicle = prop(db, w.t.id, "Ratha 2")
    f2 = trips.ensure_file(db, w.t.id, _stay(db, w.t, other_vehicle, start=4))
    with pytest.raises(HTTPException) as e:
        trips.set_crew(db, f2, CrewIn(driver_staff_id=w.driver.id, helper_staff_id=staff(db, w.t.id, "Anil").id), "u1")
    assert e.value.status_code == 409 and "Suresh" in e.value.detail


def test_start_odometer_cannot_go_below_the_vehicles_last_reading(db, w):
    f = _ready_file(db, w)
    _green_all_critical(db, f)
    _pay(db, w.stay, "126732")
    trips.refresh(db, f)
    trips.dispatch(db, f, 87396, "u1")
    trips.end_trip(db, f, 88792)
    s2 = _stay(db, w.t, w.p, start=30)
    f2 = trips.ensure_file(db, w.t.id, s2)
    trips.accept(db, f2, AcceptIn(route="Coorg", allowance_km=Decimal("700")), "u1")
    trips.set_crew(db, f2, CrewIn(driver_staff_id=w.driver.id, helper_staff_id=w.helper.id), "u1")
    _green_all_critical(db, f2)
    _pay(db, s2, "126732")
    trips.refresh(db, f2)
    with pytest.raises(HTTPException) as e:
        trips.dispatch(db, f2, 88000, "u1")
    assert e.value.status_code == 422 and "88,792" in e.value.detail


def test_the_same_bill_is_refused_twice(db, w):
    f = trips.ensure_file(db, w.t.id, w.stay)
    body = ExpenseIn(category="fuel", amount=Decimal("5330"), vendor="HP Kurnool", bill_date="2026-08-21")
    money.add_expense(db, f, body, actor_id="u1")
    with pytest.raises(HTTPException) as e:
        money.add_expense(db, f, body, actor_id="u1")
    assert e.value.status_code == 409
    money.add_expense(db, f, ExpenseIn(category="toll", amount=Decimal("890")), actor_id="u1")   # no date: never a duplicate
    money.add_expense(db, f, ExpenseIn(category="toll", amount=Decimal("890")), actor_id="u1")


def test_an_unrelated_database_error_is_not_called_a_duplicate_bill(db, w):
    """Found on PostgreSQL: any IntegrityError inside add_expense used to be reported as "bill already added"."""
    from sqlalchemy.exc import IntegrityError
    f = trips.ensure_file(db, w.t.id, w.stay)
    db.add(OpsFile(tenant_id=w.t.id, stay_id=w.stay.id, pack="caravan_rv", state="handed_over", details={}))   # 2nd file: unique break
    with pytest.raises(IntegrityError):
        money.add_expense(db, f, ExpenseIn(category="fuel", amount=Decimal("100")), actor_id="u1")
    db.rollback()


def test_extras_wait_for_a_decision_and_approval_bills_them(db, w):
    f = trips.ensure_file(db, w.t.id, w.stay)
    x = money.propose_extra(db, f, ExtraIn(kind="upsell", label="Bonfire kit", amount=Decimal("2500")), "u1")
    assert money.account(db, f)["extras_waiting"] == 1
    money.approve_extra(db, f, x.id, "u1")
    assert db.query(StayAddOn).filter_by(stay_id=w.stay.id, name="Bonfire kit").one().unit_price == Decimal("2500.00")
    with pytest.raises(HTTPException):
        money.remove_extra(db, f, x.id, "u1")
    assert money.account(db, f)["addons_total"] == Decimal("2500.00")


def test_cancelled_booking_cancels_a_file_that_has_not_left(db, w):
    f = trips.ensure_file(db, w.t.id, w.stay)
    w.stay.status = "cancelled"
    db.flush()
    assert trips.sync_files(db, w.t.id, TODAY)["cancelled"] == 1
    assert f.state == "cancelled"


def test_sync_creates_files_for_live_bookings(db, w):
    _stay(db, w.t, w.p, start=10)
    _stay(db, w.t, w.p, start=-20, nights=2)           # already over: no file
    assert trips.sync_files(db, w.t.id, TODAY)["created"] == 2
    assert trips.sync_files(db, w.t.id, TODAY)["created"] == 0


def test_another_tenant_cannot_read_a_file(db, w):
    f = trips.ensure_file(db, w.t.id, w.stay)
    other = _tenant(db)
    with pytest.raises(HTTPException) as e:
        trips.get_file(db, other.id, f.id)
    assert e.value.status_code == 404
    assert db.query(OpsJobItem).filter_by(tenant_id=other.id).count() == 0


# ── API ─────────────────────────────────────────────────────────────────────

@pytest.fixture()
def api(db, w):
    seed_capabilities(db, w.t.id)
    return type("A", (), {"mgr": _user(db, w.t.id, UserRole.MANAGER), "foh": _user(db, w.t.id, UserRole.FOH),
                          "mkt": _user(db, w.t.id, UserRole.MARKETING)})()


def test_api_open_accept_and_read(client, db, w, api):
    r = client.get(f"/api/v1/ops/files/by-stay/{w.stay.id}", headers=_h(api.mgr))
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    assert r.json()["stage"]["step_name"] == "Set up" and len(r.json()["checklist"]) == 12
    assert "phone" not in str(r.json()["stay"])
    r = client.post(f"/api/v1/ops/files/{fid}/accept", json={"route": "Coorg", "allowance_km": 700}, headers=_h(api.mgr))
    assert r.status_code == 200 and r.json()["details"]["allowance_km"] == "700"
    assert client.get("/api/v1/ops/files", headers=_h(api.foh)).json()[0]["id"] == fid


def test_api_roles(client, db, w, api):
    fid = client.get(f"/api/v1/ops/files/by-stay/{w.stay.id}", headers=_h(api.mgr)).json()["id"]
    assert client.get(f"/api/v1/ops/files/{fid}", headers=_h(api.mkt)).status_code == 403
    assert client.put(f"/api/v1/ops/files/{fid}/checklist/ac", json={"status": "green"}, headers=_h(api.foh)).status_code == 200
    assert client.post(f"/api/v1/ops/files/{fid}/dispatch", json={"reading_km": 1}, headers=_h(api.foh)).status_code == 403
    assert client.post(f"/api/v1/ops/files/{fid}/close", headers=_h(api.foh)).status_code == 403


def test_api_cross_tenant(client, db, w, api):
    fid = client.get(f"/api/v1/ops/files/by-stay/{w.stay.id}", headers=_h(api.mgr)).json()["id"]
    other = _tenant(db)
    seed_capabilities(db, other.id)
    om = _user(db, other.id, UserRole.MANAGER)
    assert client.get(f"/api/v1/ops/files/{fid}", headers=_h(om)).status_code == 404
    assert client.get(f"/api/v1/ops/files/by-stay/{w.stay.id}", headers=_h(om)).status_code == 404
    assert client.get("/api/v1/ops/files", headers=_h(om)).json() == []
