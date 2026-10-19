"""/bookings/compose: the new-booking flow. Per endpoint: happy path, a role that cannot book (403) and another workspace (not
found / nothing returned). Covers: still-needed list, pricing = the rate calculator, lead rules (new guest reuses the person and
gets a Sold lead; an open lead is marked Sold through the audited move and its hooks, on both stage paths; no open lead = no
lead), starting from a quote (prefill, marked booked, the lead's other quote closed), deposit kept out of the total, a payment
recorded now, a Razorpay link now (mocked), the confirmation (mocked send) and the clash answer.
Razorpay, WhatsApp sends, Celery and pushes are mocked: nothing leaves the test."""
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.inquiry_360 import InquiryQuote
from app.models.conversation import Message
from app.models.property import Property, Stay
from app.models.stay_finance import StayDeposit, StayInstalment, StayPayment, StayPaymentLink
from app.models.task import Task
from app.models.user import UserRole
from app.schemas.quote_calculator import CalcIn
from app.services import booking_service as bsvc
from app.services import rate_calculator as rc
from tests.test_business_data import TODAY
from tests.test_increment1_defect_specs import _h
from tests.test_quote_calculator_api import inbound, lead, person, save, w  # noqa: F401  (fixture)
from tests.test_quote_send import connect_razorpay, rzp  # noqa: F401  (fixture)

API = "/api/v1/bookings/compose"
CI = TODAY + timedelta(days=12)


@pytest.fixture(autouse=True)
def quiet():
    with patch("app.workers.tasks.invoice_tasks.notify_staff.delay"), \
         patch("app.workers.tasks.invoice_tasks.send_booking_confirmation.delay") as conf, \
         patch("app.workers.tasks.quote_tasks.cancel_payment_links.delay") as cancel, \
         patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay") as text, \
         patch("app.workers.tasks.send_whatsapp.send_whatsapp_template.delay") as tmpl:
        yield type("Q", (), {"conf": conf, "cancel": cancel, "text": text, "tmpl": tmpl})


def body(**kw):
    b = {"start_scratch": True, "mode": "fixed", "package_key": "coorg-48", "check_in": CI.isoformat(),
         "check_out": (CI + timedelta(days=2)).isoformat(), "check_in_time": "12:00", "check_out_time": "12:00", "guests": 5,
         "interior": "Black", "pickup": "HSR Layout", "gst_percent": "18", "prices_include_gst": True, "deposit_amount": "10000",
         "payment": {"kind": "none"}, "confirmation": "later"}
    b.update(kw)
    return b


def go(client, user, **kw):
    return client.post(API, json=body(**kw), headers=_h(user))


def sold(w):
    return w.stages["sold"].id


# ─── setup / preview ──────────────────────────────────────────────────────────────────────────────────────

def test_setup_lists_packages_caravans_and_sources_and_needs_a_booking_role(client, db, w):
    out = client.get(f"{API}/setup", headers=_h(w.res)).json()
    assert {p["key"] for p in out["packages"]} >= {"coorg-48", "day-rate"}
    assert [v["name"] for v in out["vehicles"]] == ["Ratha 1", "Ratha 2"]
    assert {"value": "instagram", "label": "Instagram"} in out["sources"] and out["advance_days"] == 2
    assert client.get(f"{API}/setup", headers=_h(w.foh)).status_code == 403


def test_preview_says_what_is_still_needed_and_writes_nothing(client, db, w):
    before = (db.query(Stay).count(), db.query(Inquiry).count())
    out = client.post(f"{API}/preview", json={"guests": 2}, headers=_h(w.res)).json()
    msgs = {(p["section"], p["message"]) for p in out["problems"]}
    assert ("guest", "Pick the guest, or add a new one with their phone number.") in msgs
    assert ("trip", "Pick a package, or Custom trip.") in msgs and ("trip", "Pick a check-in date.") in msgs
    assert (db.query(Stay).count(), db.query(Inquiry).count()) == before


def test_preview_prices_with_the_rate_calculator_and_shows_both_caravans(client, db, w):
    g = person(db, w.t.id)
    out = client.post(f"{API}/preview", json=body(guest_id=g.id, addons=[{"name": "Culinary kit", "price": "5000", "unit": "one_time"}],
                                                  discount_percent="5"), headers=_h(w.res)).json()
    assert out["problems"] == []
    calc = rc.compute(db, w.t, CalcIn(mode="fixed", package_key="coorg-48", start_date=CI, days=2, guests=5, gst_percent=Decimal("18"),
                                      prices_include_gst=True, discount_percent=Decimal("5"),
                                      addons=[{"name": "Culinary kit", "price": "5000", "unit": "one_time"}]), today=TODAY)
    assert Decimal(out["price"]["total"]) == calc.t["total"] and out["schedule"]["advance"] == str(rc.rupee(calc.t["total"] / 2))
    assert [v["state"] for v in out["vehicles"]["vehicles"]] == ["free", "free"] and out["vehicle"]["name"] == "Ratha 1"
    assert out["schedule"]["advance_due"] == (TODAY + timedelta(days=2)).isoformat()      # owner decision 3
    assert out["schedule"]["balance_due"] == CI.isoformat()                               # before pickup
    assert "Interior: Black. Pickup: HSR Layout. Add-ons (in the price): Culinary kit." == out["staff_notes"]
    assert "your Test" not in (out["message_text"] or "") and "Booking number: given when you create it" in out["message_text"]


# ─── create: lead rules ───────────────────────────────────────────────────────────────────────────────────

def test_a_new_guest_with_a_known_number_reuses_the_person_and_gets_a_sold_lead(client, db, w):
    known = person(db, w.t.id, name="Kiran Reddy", phone="+919876512678")       # e.g. a mirrored chat, no lead
    guests_before = db.query(Guest).filter_by(tenant_id=w.t.id).count()
    r = go(client, w.res, new_guest={"phone": "98765 12678", "name": "Kiran", "source": "instagram"}, start_scratch=False)
    assert r.status_code == 201, r.text
    out = r.json()
    assert db.query(Guest).filter_by(tenant_id=w.t.id).count() == guests_before
    stay = db.query(Stay).filter_by(id=out["booking_id"]).one()
    assert stay.guest_id == known.id and stay.inquiry_id
    inq = db.query(Inquiry).filter_by(id=stay.inquiry_id).one()
    assert inq.source == InquirySource.META_IG and inq.stage_id == sold(w) and inq.guest_id == known.id
    assert any(i["kind"] == "lead" and i["done"] and "lead from Instagram marked Sold" in i["text"] for i in out["items"])


def test_a_brand_new_guest_gets_a_person_and_a_sold_lead(client, db, w):
    r = go(client, w.res, new_guest={"phone": "+91 99001 12211", "name": "Anita Rao", "source": "whatsapp"}, start_scratch=False)
    assert r.status_code == 201, r.text
    stay = db.query(Stay).filter_by(id=r.json()["booking_id"]).one()
    assert stay.guest.name == "Anita Rao" and db.query(Inquiry).filter_by(id=stay.inquiry_id).one().stage_id == sold(w)


@pytest.mark.parametrize("legacy", [False, True])
def test_an_open_lead_is_marked_sold_through_the_audited_move_and_its_hooks(client, db, w, legacy):
    inq = lead(db, w, legacy=legacy)
    with patch("app.services.inquiry_service._notify_stage_hooks") as hooks:
        r = go(client, w.res, guest_id=inq.guest_id)
    assert r.status_code == 201, r.text
    assert hooks.called
    db.expire_all()
    got = db.query(Inquiry).filter_by(id=inq.id).one()
    assert got.stage_id == sold(w) and db.query(Stay).filter_by(id=r.json()["booking_id"]).one().inquiry_id == inq.id
    assert db.query(Stay).filter_by(inquiry_id=inq.id).count() == 1                 # the won-lead hook made no second booking


def test_a_known_guest_without_an_open_lead_gets_no_lead(client, db, w):
    g = person(db, w.t.id)
    before = db.query(Inquiry).filter_by(tenant_id=w.t.id).count()
    r = go(client, w.res, guest_id=g.id)
    assert r.status_code == 201, r.text
    assert db.query(Inquiry).filter_by(tenant_id=w.t.id).count() == before
    assert db.query(Stay).filter_by(id=r.json()["booking_id"]).one().inquiry_id is None
    assert any(i["kind"] == "lead" and not i["done"] for i in r.json()["items"])


# ─── create: quote, money, pricing ────────────────────────────────────────────────────────────────────────

def test_start_from_a_quote_prefills_and_marks_it_booked_and_closes_the_other(client, db, w):
    inq = lead(db, w)
    old = save(client, w.res, inq, action="save", guests=4).json()["quote_id"]
    new = save(client, w.res, inq, action="save").json()["quote_id"]
    ctx = client.get(f"{API}/context", params={"inquiry_id": inq.id}, headers=_h(w.res)).json()
    card = next(q for q in ctx["quotes"] if q["quote_id"] == new)
    assert card["usable"] and card["prefill"]["package_key"] == "coorg-48" and card["prefill"]["guests"] == 5
    assert card["prefill"]["check_in"] == (TODAY + timedelta(days=12)).isoformat()
    still = client.post(f"{API}/preview", json=body(guest_id=inq.guest_id, start_scratch=False), headers=_h(w.res)).json()
    assert {"section": "guest", "message": "Pick one of the saved quotes, or choose Start from scratch.", "live": False} in still["problems"]
    r = go(client, w.res, guest_id=inq.guest_id, start_scratch=False, quote_id=new)
    assert r.status_code == 201, r.text
    db.expire_all()
    assert db.query(InquiryQuote).filter_by(id=new).one().status == "accepted"
    olds = db.query(InquiryQuote).filter_by(id=old).one()
    assert olds.status in ("withdrawn", "superseded")
    ctx2 = client.get(f"{API}/context", params={"guest_id": inq.guest_id}, headers=_h(w.res)).json()
    booked = next(q for q in ctx2["quotes"] if q["quote_id"] == new)
    assert booked["booked"]["booking_id"] == r.json()["booking_id"] and not booked["usable"]


def test_price_equals_the_calculator_and_the_deposit_is_never_in_the_total(client, db, w):
    g = person(db, w.t.id)
    r = go(client, w.res, guest_id=g.id, deposit_amount="15000")
    stay = db.query(Stay).filter_by(id=r.json()["booking_id"]).one()
    assert stay.total_amount == Decimal("70000.00") and stay.gst_percent == Decimal("18")
    fin = bsvc.financials_for(db, w.t.id, [stay])[stay.id]
    assert fin["total"] == 70000.0 and fin["paid"] == 0.0                      # 15,000 deposit not in owed or paid
    assert db.query(StayDeposit).filter_by(stay_id=stay.id).one().amount == Decimal("15000")
    sched = sorted((i.label, i.amount, i.due_date) for i in db.query(StayInstalment).filter_by(stay_id=stay.id).all())
    assert sched == [("Advance 50%", Decimal("35000"), TODAY + timedelta(days=2)), ("Balance", Decimal("35000"), CI)]
    assert stay.internal_notes.startswith("Interior: Black. Pickup: HSR Layout.") and stay.check_in_time == "12:00"
    assert db.query(Task).filter_by(tenant_id=w.t.id, guest_id=g.id).count() == 2          # advance + balance reminders


def test_paid_now_records_the_payment_and_needs_a_reference(client, db, w):
    g = person(db, w.t.id)
    bad = go(client, w.res, guest_id=g.id, payment={"kind": "paid", "method": "upi"})
    assert bad.status_code == 422 and bad.json()["detail"]["problems"][0]["section"] == "pay"
    r = go(client, w.res, guest_id=g.id, payment={"kind": "paid", "method": "upi", "reference": "429817364512"})
    assert r.status_code == 201, r.text
    pay = db.query(StayPayment).filter_by(stay_id=r.json()["booking_id"]).one()
    assert (pay.amount, pay.method, pay.reference) == (Decimal("35000"), "upi", "429817364512")
    assert any(i["kind"] == "payment" and i["done"] and "₹35,000 recorded: UPI" in i["text"] for i in r.json()["items"])


def test_link_now_makes_a_razorpay_link_after_the_booking(client, db, w, rzp):
    g = person(db, w.t.id)
    assert go(client, w.res, guest_id=g.id, payment={"kind": "link"}).status_code == 422          # Razorpay not connected
    connect_razorpay(db, w.t.id)
    r = go(client, w.res, guest_id=g.id, payment={"kind": "link"})
    assert r.status_code == 201, r.text
    assert rzp.create.call_args.kwargs["amount_inr"] == 35000.0
    assert db.query(StayPaymentLink).filter_by(stay_id=r.json()["booking_id"]).count() == 1
    assert any(i["kind"] == "link" for i in r.json()["items"])          # template not approved here: said, not hidden


def test_confirmation_in_the_24h_window_is_a_normal_message(client, db, w, quiet):
    g = person(db, w.t.id, phone="+919845067110")
    inbound(db, w.t.id, g.id)
    r = go(client, w.res, guest_id=g.id, confirmation="now", attach_invoice=False)
    assert r.status_code == 201, r.text
    msg = db.query(Message).filter_by(tenant_id=w.t.id, idempotency_key=f"bk:{r.json()['booking_id']}:confirmed").one()
    assert "booking is confirmed" in msg.body and r.json()["ref"] in msg.body and quiet.text.called
    assert any(i["kind"] == "confirmation" and i["done"] for i in r.json()["items"])


def test_both_caravans_taken_is_refused_with_the_reason(client, db, w):
    for _ in range(2):
        assert go(client, w.res, guest_id=person(db, w.t.id).id).status_code == 201
    r = go(client, w.res, guest_id=person(db, w.t.id).id)
    assert r.status_code == 422
    p = r.json()["detail"]["problems"][0]
    assert p["section"] == "veh" and p["message"].startswith("Both caravans are booked on these dates")


# ─── roles and workspaces ─────────────────────────────────────────────────────────────────────────────────

def test_a_role_that_cannot_book_is_refused(client, db, w):
    g = person(db, w.t.id)
    assert go(client, w.foh, guest_id=g.id).status_code == 403
    assert client.post(f"{API}/preview", json=body(), headers=_h(w.foh)).status_code == 403
    assert client.get(f"{API}/guests", params={"q": "Kiran"}, headers=_h(w.foh)).status_code == 403


def test_another_workspace_is_never_found(client, db, w):
    from tests.test_quote_builder_pricing import ratha
    other = ratha(db)
    from app.services.pipeline_stage_service import seed_default_pipeline_stages
    other.stages = {s.key: s for s in seed_default_pipeline_stages(db, other.t.id)}
    db.commit()
    theirs = lead(db, other)
    assert client.get(f"{API}/context", params={"inquiry_id": theirs.id}, headers=_h(w.res)).status_code == 404
    r = go(client, w.res, guest_id=theirs.guest_id)
    assert r.status_code == 422 and r.json()["detail"]["problems"][0]["message"].startswith("That guest was not found")
    hits = client.get(f"{API}/guests", params={"q": "Kiran"}, headers=_h(w.res)).json()["results"]
    assert all(h["guest_id"] != theirs.guest_id for h in hits)
    assert db.query(Stay).filter_by(tenant_id=other.t.id).count() == 0
    assert db.query(Property).filter_by(tenant_id=other.t.id).count() == 2


def test_the_duplicate_number_check(client, db, w):
    known = person(db, w.t.id, name="Kiran Reddy", phone="+919876512678")
    out = client.get(f"{API}/guests", params={"phone": "98765 12678"}, headers=_h(w.res)).json()
    assert out["valid"] and out["existing"]["guest_id"] == known.id and out["existing"]["phone_last4"] == "2678"
    assert client.get(f"{API}/guests", params={"phone": "98765"}, headers=_h(w.res)).json() == {"valid": False, "digits": 5, "existing": None}


# ─── services directly: happy path + another workspace ────────────────────────────────────────────────────

def test_people_search_and_context_stay_in_the_workspace(db, w):
    from app.services import booking_compose_people as people
    from tests.test_quote_builder_pricing import ratha
    mine = person(db, w.t.id, name="Kiran Reddy")
    other = ratha(db)
    theirs = person(db, other.t.id, name="Kiran Reddy")
    hits = people.search(db, w.t.id, "Kiran")["results"]
    assert [h["guest_id"] for h in hits] == [mine.id] and hits[0]["tag"] == "Guest · no open lead"
    with pytest.raises(people.PeopleError):
        people.context(db, w.t.id, guest_id=theirs.id)
    assert people.context(db, w.t.id, guest_id=mine.id)["guest"]["guest_id"] == mine.id


def test_evaluate_prices_and_never_sees_another_workspaces_guest(db, w):
    from app.schemas.booking_compose import ComposeIn
    from app.services import booking_compose_service as svc
    from tests.test_quote_builder_pricing import ratha
    g = person(db, w.t.id)
    plan = svc.evaluate(db, w.res, ComposeIn(**body(guest_id=g.id)))
    assert plan.problems == [] and plan.total == Decimal("70000.00") and plan.prop.name == "Ratha 1"
    assert plan.advance == Decimal("35000") and plan.balance_due == CI
    other = ratha(db)
    stranger = person(db, other.t.id)
    plan = svc.evaluate(db, w.res, ComposeIn(**body(guest_id=stranger.id)))
    assert plan.guest is None and plan.problems[0]["section"] == "guest"


def test_the_confirmation_text_and_its_delivery_outside_the_window(db, w, quiet):
    from app.services import booking_compose_send as send
    text = send.confirmation_text(greeting="Namaskara", brand="Ratha", guest_name="Sharath N.", ref="#AB12CD34", title="Kabini",
                                  vehicle="Ratha 1", check_in=CI, check_in_time="07:00", check_out=CI + timedelta(days=1),
                                  check_out_time="20:00", guests=8, pickup="Koramangala", total=Decimal("65000"), gst=Decimal("9915"),
                                  paid=Decimal("0"), advance=Decimal("32500"), advance_due=TODAY + timedelta(days=2), link_url=None,
                                  balance=Decimal("32500"), balance_rule="pickup", balance_due=CI, deposit=Decimal("10000"),
                                  deposit_collect="pickup", invoice="INV/2026-27/0094")
    assert text.splitlines()[0] == "Namaskara Sharath, your Ratha booking is confirmed."
    assert "Ratha 1 · " in text and "7:00 am" in text and "Total ₹65,000 (incl. GST)" in text and "Balance ₹32,500 before pickup" in text
    assert text.endswith("Invoice INV/2026-27/0094 attached.")
    stay = db.query(Stay).filter_by(id=go_create(db, w)).one()
    with patch("app.services.wa_booking_messages.send_confirmation", return_value={"status": "skipped", "reason": "template not approved"}) as sc:
        out = send.deliver_confirmation(db, w.t.id, stay.id, None, "x", "template")
    assert sc.called and out["status"] == "skipped"
    from tests.test_quote_builder_pricing import ratha
    other = ratha(db)
    assert send.deliver_confirmation(db, other.t.id, stay.id, None, "x", "template") == {"status": "ignored"}


def go_create(db, w) -> str:
    from app.schemas.booking_compose import ComposeIn
    from app.services import booking_compose_create as create
    return create.compose(db, w.res, ComposeIn(**body(guest_id=person(db, w.t.id).id)))["booking_id"]
