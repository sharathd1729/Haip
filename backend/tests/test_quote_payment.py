"""A paid quote link becomes a booking (quote_payment_service, via the signed Razorpay webhook).

Paid -> Stay with the quote's numbers, payment recorded once, quote accepted + the other option withdrawn + its link
cancelled (queued), lead closed-won, invoices.after_payment queued. Vehicle taken -> no booking, staff task. Second option
paid after the first was booked -> staff task, never a second booking. Duplicate webhook -> ignored. Razorpay is mocked.
"""
import hashlib
import hmac
import json
import uuid
from datetime import timedelta
from unittest.mock import patch

import pytest

from app.adapters.payments import razorpay as rzp_adapter
from app.models.audit_event import AuditEvent
from app.models.inquiry import Inquiry
from app.models.inquiry_360 import InquiryQuote
from app.models.pipeline_stage import PipelineStage
from app.models.property import Property, Stay
from app.models.stay_finance import StayPayment, StayPaymentLink
from app.models.task import Task
from app.services import quote_payment_service
from app.services.pipeline_stage_service import seed_default_pipeline_stages
from tests.test_increment1_defect_specs import _h
from tests.test_quote_builder_pricing import START
from tests.test_quote_send import WEBHOOK_SECRET, ready, rzp, w  # noqa: F401  (fixtures)
from tests.test_quotes_api import API


@pytest.fixture()
def q():
    with patch("app.workers.tasks.invoice_tasks.after_payment.delay") as after, \
         patch("app.workers.tasks.invoice_tasks.notify_staff.delay") as notify, \
         patch("app.workers.tasks.quote_tasks.cancel_payment_links.delay") as cancel:
        yield type("Q", (), {"after": after, "notify": notify, "cancel": cancel})


def _webhook(client, slug, link_id, pay_id, paise):
    body = json.dumps({"event": "payment_link.paid", "payload": {
        "payment_link": {"entity": {"id": link_id, "amount_paid": paise}},
        "payment": {"entity": {"id": pay_id, "amount": paise, "method": "upi"}}}}).encode()
    sig = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return client.post(f"/api/v1/webhooks/razorpay/{slug}", content=body, headers={"x-razorpay-signature": sig})


def _sent(client, db, w, **kw):
    """A saved quote (primary + fallback) on a lead in the default entry stage, sent: two live links."""
    seed_default_pipeline_stages(db, w.t.id)
    inq, quotes = ready(client, db, w, **kw)
    entry = db.query(PipelineStage).filter_by(tenant_id=w.t.id, is_default_entry=True).first()
    db.query(Inquiry).filter_by(id=inq.id).update({"stage_id": entry.id})
    db.commit()
    assert client.post(f"{API}/{quotes[0]['id']}/send", headers=_h(w.owner)).status_code == 200
    links = {lk.inquiry_quote_id: lk for lk in db.query(StayPaymentLink).filter_by(tenant_id=w.t.id).all()}
    return inq, quotes, links


def _paise(link):
    return int(round(float(link.amount) * 100))


def test_paid_quote_link_books_the_quote(client, db, w, rzp, q):
    inq, (p, f), links = _sent(client, db, w)
    lp, lf = links[p["id"]], links[f["id"]]
    res = _webhook(client, w.t.slug, lp.external_id, "pay_Q1", _paise(lp))
    assert res.status_code == 200 and res.json()["status"] == "booked"
    db.expire_all()
    stay = db.query(Stay).filter_by(tenant_id=w.t.id).one()
    assert stay.inquiry_id == inq.id and stay.guest_id == inq.guest_id and float(stay.total_amount) == 89880
    assert (stay.check_in, stay.check_out, stay.adults, stay.children) == (START, START + timedelta(days=2), 5, 1)
    assert stay.channel_source == "direct" and db.query(Property).filter_by(id=stay.property_id).one().name == "Ratha 1"
    assert stay.internal_notes.startswith("Booked from quote Q-")
    pay = db.query(StayPayment).filter_by(tenant_id=w.t.id).one()
    assert (pay.stay_id, float(pay.amount), pay.method, pay.external_id) == (stay.id, 44940, "razorpay", "pay_Q1")
    quotes = {r.id: r for r in db.query(InquiryQuote).filter_by(tenant_id=w.t.id).all()}
    assert quotes[p["id"]].status == "accepted" and quotes[f["id"]].status == "withdrawn"
    assert db.query(StayPaymentLink).filter_by(id=lp.id).one().stay_id == stay.id
    won = db.query(PipelineStage).filter_by(tenant_id=w.t.id, is_closed_won=True).one()
    assert db.query(Inquiry).filter_by(id=inq.id).one().stage_id == won.id
    q.after.assert_called_once_with(tenant_id=w.t.id, payment_id=pay.id)
    q.cancel.assert_called_once_with(tenant_id=w.t.id, link_ids=[lf.id])
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="quote.accepted").count() == 1
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="booking.created").count() == 1

    # Razorpay retries the same delivery: nothing new
    again = _webhook(client, w.t.slug, lp.external_id, "pay_Q1", _paise(lp))
    assert again.json()["status"] == "duplicate"
    db.expire_all()
    assert db.query(Stay).filter_by(tenant_id=w.t.id).count() == 1 and db.query(StayPayment).filter_by(tenant_id=w.t.id).count() == 1
    assert q.after.call_count == 1

    journey = client.get(f"{API}/{p['id']}", headers=_h(w.owner)).json()["send"]
    assert journey["booking_id"] == stay.id and journey["paid"]["option_rank"] == 1 and journey["polling"] is False


def test_second_option_paid_later_raises_a_task_not_a_booking(client, db, w, rzp, q):
    _inq, (p, f), links = _sent(client, db, w)
    _webhook(client, w.t.slug, links[p["id"]].external_id, "pay_A", _paise(links[p["id"]]))
    res = _webhook(client, w.t.slug, links[f["id"]].external_id, "pay_B", _paise(links[f["id"]]))
    assert res.json()["status"] == "double_payment"
    db.expire_all()
    assert db.query(Stay).filter_by(tenant_id=w.t.id).count() == 1 and db.query(StayPayment).filter_by(tenant_id=w.t.id).count() == 1
    task = db.query(Task).filter(Task.tenant_id == w.t.id, Task.title.like("Possible double payment%")).one()
    assert task.priority == "high" and "pay_B" in task.title
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="quote.payment_after_booking").count() == 1


def test_vehicle_taken_means_no_booking_and_a_staff_task(client, db, w, rzp, q):
    r1 = db.query(Property).filter_by(tenant_id=w.t.id, name="Ratha 1").one()
    _inq, (p, _f), links = _sent(client, db, w, vehicle_property_id=r1.id)
    other = Stay(id=str(uuid.uuid4()), tenant_id=w.t.id, guest_id=_inq.guest_id, property_id=r1.id, check_in=START,
                 check_out=START + timedelta(days=1), status="confirmed", total_amount=1)
    db.add(other)
    db.commit()
    lp = links[p["id"]]
    res = _webhook(client, w.t.slug, lp.external_id, "pay_X", _paise(lp))
    assert res.json()["status"] == "paid_no_vehicle"
    db.expire_all()
    assert db.query(Stay).filter_by(tenant_id=w.t.id).count() == 1                           # only the one that took the caravan
    assert db.query(StayPayment).filter_by(tenant_id=w.t.id).count() == 0
    assert db.query(StayPaymentLink).filter_by(id=lp.id).one().status == "paid"              # the payment stays on the link
    assert db.query(InquiryQuote).filter_by(id=p["id"]).one().status == "issued"             # staff decide
    task = db.query(Task).filter(Task.tenant_id == w.t.id, Task.title.like("Paid, but the caravan is no longer free%")).one()
    assert task.priority == "high" and "pay_X" in task.title and "Rs. 44,940" in task.title
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="quote.paid_no_vehicle").count() == 1
    assert not q.after.called and not q.cancel.called
    assert _webhook(client, w.t.slug, lp.external_id, "pay_X", _paise(lp)).json()["status"] == "duplicate"


def test_both_caravans_taken(client, db, w, rzp, q):
    inq, (p, _f), links = _sent(client, db, w)
    for prop in db.query(Property).filter_by(tenant_id=w.t.id).all():
        db.add(Stay(id=str(uuid.uuid4()), tenant_id=w.t.id, guest_id=inq.guest_id, property_id=prop.id, check_in=START,
                    check_out=START + timedelta(days=2), status="confirmed", total_amount=1))
    db.commit()
    lp = links[p["id"]]
    assert _webhook(client, w.t.slug, lp.external_id, "pay_Y", _paise(lp)).json()["status"] == "paid_no_vehicle"


def test_cancelling_the_other_link(db, w, rzp, client, q):
    _inq, (p, f), links = _sent(client, db, w)
    lf = links[f["id"]]
    with patch("app.adapters.payments.razorpay.cancel_payment_link") as cancel:
        assert quote_payment_service.cancel_links(db, w.t.id, [lf.id]) == {lf.id: "cancelled"}
    cancel.assert_called_once_with("rzp_test_k", "s", lf.external_id)
    db.expire_all()
    assert db.query(StayPaymentLink).filter_by(id=lf.id).one().status == "cancelled"
    lp = links[p["id"]]
    with patch("app.adapters.payments.razorpay.cancel_payment_link", side_effect=rzp_adapter.RazorpayError("down")):
        assert quote_payment_service.cancel_links(db, w.t.id, [lp.id]) == {lp.id: "failed"}
    db.expire_all()
    assert db.query(StayPaymentLink).filter_by(id=lp.id).one().status == "created"
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="quote.payment_link_cancel_failed").count() == 1


def test_another_tenants_webhook_cannot_touch_the_link(client, db, w, rzp, q):
    from tests.test_business_data import _tenant
    from tests.test_quote_send import connect_razorpay
    _inq, (p, _f), links = _sent(client, db, w)
    other = _tenant(db)
    connect_razorpay(db, other.id)
    res = _webhook(client, other.slug, links[p["id"]].external_id, "pay_Z", 4494000)
    assert res.json()["status"] == "ignored"
    db.expire_all()
    assert db.query(StayPaymentLink).filter_by(id=links[p["id"]].id).one().status == "created"
