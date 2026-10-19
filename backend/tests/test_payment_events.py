"""Paid payment links: webhook idempotency, invoice + WhatsApp follow-ups, quote links, booking messages, reminders."""
import hashlib
import hmac
import json
import os
import uuid
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.exc import IntegrityError

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

pytestmark = pytest.mark.usefixtures("capabilities_seeded")

from app.api.v1.endpoints.messaging import TemplateCategory, TemplateStatus, WATemplate  # noqa: E402
from app.core.encryption import encrypt_credentials  # noqa: E402
from app.models.audit_event import AuditEvent  # noqa: E402
from app.models.base import gen_uuid  # noqa: E402
from app.models.conversation import Message  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.inquiry import Inquiry  # noqa: E402
from app.models.inquiry_360 import InquiryQuote  # noqa: E402
from app.models.integration import Integration  # noqa: E402
from app.models.invoice import Invoice  # noqa: E402
from app.models.property import Property, Stay  # noqa: E402
from app.models.stay_finance import StayInstalment, StayPayment, StayPaymentLink  # noqa: E402
from app.models.task import Task  # noqa: E402
from app.services import balance_reminder_service, payment_followup_service, wa_booking_messages, wa_booking_pack  # noqa: E402

SECRET = "whsec_test_123"
PROFILE = {"legal_name": "Ratha Journeys LLP", "gstin": "29AAGCB7383J1Z4", "address": "Jakkur, Bengaluru", "state_code": "29",
           "gst_rate": 12, "invoice_prefix": "INV", "receipt_prefix": "RCPT"}


@pytest.fixture()
def q():
    """Every queue the code under test can reach, mocked (no broker, no Meta, no storage)."""
    with patch("app.workers.tasks.invoice_tasks.after_payment.delay") as after, \
         patch("app.workers.tasks.invoice_tasks.notify_staff.delay") as notify, \
         patch("app.workers.tasks.invoice_tasks.render_pdf.delay"), \
         patch("app.workers.tasks.send_whatsapp.send_whatsapp_template.delay") as send, \
         patch("app.services.media_storage.upload_invoice_pdf", side_effect=lambda tid, iid, pdf: f"{tid}/invoices/{iid}.pdf") as up, \
         patch("app.services.push_service.send_to_tenant") as push:
        yield type("Q", (), {"after": after, "notify": notify, "send": send, "upload": up, "push": push})


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _setup(db, tu, total=20000, approve=True, razorpay=True):
    tenant = tu["tenant"]
    tenant.brand_config = {"invoice_profile": dict(PROFILE)}
    prop = Property(id=gen_uuid(), tenant_id=tenant.id, name="Ratha 1", slug=f"r-{uuid.uuid4().hex[:6]}", type="villa", is_active=True)
    guest = Guest(id=gen_uuid(), tenant_id=tenant.id, name="Kiran Rao", phone=f"+9199{uuid.uuid4().int % 10**8:08d}")
    db.add_all([prop, guest])
    db.flush()
    stay = Stay(id=gen_uuid(), tenant_id=tenant.id, guest_id=guest.id, property_id=prop.id, check_in=date.today() + timedelta(days=10),
                check_out=date.today() + timedelta(days=12), adults=2, status="confirmed", total_amount=total, channel_source="direct")
    db.add(stay)
    if razorpay:
        db.add(Integration(tenant_id=tenant.id, kind="razorpay", status="active", config={},
                           credentials_kms_blob=encrypt_credentials({"key_id": "rzp_test_abc12345", "key_secret": "s3cret", "webhook_secret": SECRET})))
    if approve:
        _approve(db, tenant.id)
    db.commit()
    return stay


def _approve(db, tenant_id, names=None):
    for t in wa_booking_pack.PACK:
        if names and t["name"] not in names:
            continue
        db.add(WATemplate(tenant_id=tenant_id, name=t["name"], language="en", category=TemplateCategory.UTILITY,
                          status=TemplateStatus.APPROVED, components=t["components"]))
    db.commit()


def _post(client, slug, payload):
    body = json.dumps(payload).encode()
    sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    return client.post(f"/api/v1/webhooks/razorpay/{slug}", content=body, headers={"x-razorpay-signature": sig})


def _paid(link_id, pay_id, paise):
    return {"event": "payment_link.paid", "payload": {"payment_link": {"entity": {"id": link_id, "amount_paid": paise}},
                                                      "payment": {"entity": {"id": pay_id, "amount": paise, "method": "upi"}}}}


# ── Webhook ──────────────────────────────────────────────────────────────────

def test_unique_index_rejects_a_second_row_for_one_razorpay_payment(db, tenant_and_user):
    stay = _setup(db, tenant_and_user, approve=False)
    tid = tenant_and_user["tenant"].id
    db.add(StayPayment(tenant_id=tid, stay_id=stay.id, amount=1, method="razorpay", external_id="pay_same", paid_on=date.today()))
    db.flush()
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(StayPayment(tenant_id=tid, stay_id=stay.id, amount=1, method="razorpay", external_id="pay_same", paid_on=date.today()))
            db.flush()
    db.add(StayPayment(tenant_id=tid, stay_id=stay.id, amount=1, method="cash", paid_on=date.today()))   # NULLs never clash
    db.add(StayPayment(tenant_id=tid, stay_id=stay.id, amount=1, method="cash", paid_on=date.today()))
    db.flush()


def test_paid_link_records_once_and_queues_followup(client, db, tenant_and_user, q):
    stay = _setup(db, tenant_and_user)
    tid, slug = tenant_and_user["tenant"].id, tenant_and_user["tenant"].slug
    db.add(StayPaymentLink(tenant_id=tid, stay_id=stay.id, external_id="plink_1", short_url="https://rzp.io/i/AbC", amount=8000))
    db.commit()
    assert _post(client, slug, _paid("plink_1", "pay_1", 800000)).json()["status"] == "recorded"
    assert _post(client, slug, _paid("plink_1", "pay_1", 800000)).json()["status"] == "duplicate"     # Razorpay retry
    pays = db.query(StayPayment).filter_by(tenant_id=tid, stay_id=stay.id).all()
    assert len(pays) == 1 and float(pays[0].amount) == 8000
    q.after.assert_called_once_with(tenant_id=tid, payment_id=pays[0].id)                            # slow work queued, once
    assert db.query(Invoice).filter_by(tenant_id=tid).count() == 0                                     # nothing slow inline


# ── Follow-up task (invoice, PDF, WhatsApp, push) ────────────────────────────

def test_first_payment_invoice_pdf_and_confirmation(db, tenant_and_user, q):
    stay = _setup(db, tenant_and_user)
    tenant = tenant_and_user["tenant"]
    pay = StayPayment(tenant_id=tenant.id, stay_id=stay.id, amount=8000, method="razorpay", external_id="pay_a", reference="pay_a", paid_on=date.today())
    db.add(pay)
    db.commit()
    res = payment_followup_service.after_payment(db, tenant.id, pay.id)
    assert res["status"] == "done" and res["kind"] == "invoice" and res["message"] == "queued"
    inv = db.query(Invoice).filter_by(tenant_id=tenant.id, payment_id=pay.id).one()
    assert inv.kind == "invoice" and float(inv.total) == 20000 and float(inv.amount_received) == 8000 and inv.pdf_media_key
    assert q.upload.call_args.args[2].startswith(b"%PDF-")
    msg = db.query(Message).filter_by(tenant_id=tenant.id).one()
    assert msg.channel_metadata["template_name"] == wa_booking_pack.BOOKING_CONFIRMED
    assert msg.channel_metadata["document"] == {"key": inv.pdf_media_key, "filename": f"Invoice {inv.number.replace('/', '-')}.pdf"}
    variables = q.send.call_args.kwargs["variables"]
    assert variables[0] == "Kiran" and variables[6] == "₹8,000" and variables[7] == "₹12,000" and "Rs." not in msg.body
    assert q.push.called

    again = payment_followup_service.after_payment(db, tenant.id, pay.id)     # task retried: nothing doubles
    assert again["message"] == "duplicate" and db.query(Invoice).filter_by(tenant_id=tenant.id).count() == 1
    assert q.send.call_count == 1 and q.upload.call_count == 1


def test_later_payment_gets_receipt_and_payment_received(db, tenant_and_user, q):
    stay = _setup(db, tenant_and_user)
    tid = tenant_and_user["tenant"].id
    first = StayPayment(tenant_id=tid, stay_id=stay.id, amount=8000, method="razorpay", external_id="pay_a", paid_on=date.today())
    db.add(first)
    db.commit()
    payment_followup_service.after_payment(db, tid, first.id)
    second = StayPayment(tenant_id=tid, stay_id=stay.id, amount=12000, method="razorpay", external_id="pay_b", reference="pay_b", paid_on=date.today())
    db.add(second)
    db.commit()
    res = payment_followup_service.after_payment(db, tid, second.id)
    assert res["kind"] == "receipt" and res["message"] == "queued"
    rec = db.query(Invoice).filter_by(tenant_id=tid, payment_id=second.id).one()
    inv = db.query(Invoice).filter_by(tenant_id=tid, kind="invoice").one()
    assert rec.number.startswith("RCPT/") and rec.invoice_id == inv.id and float(rec.balance_due) == 0 and inv.status == "issued"
    last = q.send.call_args.kwargs
    assert last["template_name"] == wa_booking_pack.PAYMENT_RECEIVED and last["variables"][3] == "Your trip is fully paid."


def test_no_invoice_details_means_no_invoice_and_staff_told(db, tenant_and_user, q):
    stay = _setup(db, tenant_and_user)
    tenant = tenant_and_user["tenant"]
    tenant.brand_config = {}
    pay = StayPayment(tenant_id=tenant.id, stay_id=stay.id, amount=100, method="razorpay", external_id="pay_x", paid_on=date.today())
    db.add(pay)
    db.commit()
    assert payment_followup_service.after_payment(db, tenant.id, pay.id)["status"] == "no_invoice"
    assert db.query(Invoice).count() == 0 and q.send.call_count == 0 and q.push.called
    assert db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="booking.invoice_not_issued").count() == 1


# ── Quote link (no booking yet) ──────────────────────────────────────────────

def test_paid_quote_link_raises_staff_task_and_makes_no_booking(client, db, tenant_and_user, q):
    tenant = tenant_and_user["tenant"]
    _setup(db, tenant_and_user)
    guest = Guest(id=gen_uuid(), tenant_id=tenant.id, name="Asha", phone="+919812345678")
    db.add(guest)
    db.flush()
    inq = Inquiry(id=gen_uuid(), tenant_id=tenant.id, guest_id=guest.id, assigned_to=tenant_and_user["user"].id)
    db.add(inq)
    db.flush()
    quote = InquiryQuote(tenant_id=tenant.id, inquiry_id=inq.id, amount=44940)
    db.add(quote)
    db.flush()
    db.add(StayPaymentLink(tenant_id=tenant.id, stay_id=None, inquiry_quote_id=quote.id, external_id="plink_q",
                           short_url="https://rzp.io/i/Q", amount=22470))
    db.commit()
    stays_before = db.query(Stay).filter_by(tenant_id=tenant.id).count()

    assert _post(client, tenant.slug, _paid("plink_q", "pay_q", 2247000)).json()["status"] == "quote_recorded"
    assert _post(client, tenant.slug, _paid("plink_q", "pay_q", 2247000)).json()["status"] == "duplicate"
    task = db.query(Task).filter_by(tenant_id=tenant.id, inquiry_id=inq.id).one()
    assert task.title.startswith("Payment received for quote") and "create the booking" in task.title and task.priority == "high"
    assert task.assigned_to == tenant_and_user["user"].id
    assert db.query(Stay).filter_by(tenant_id=tenant.id).count() == stays_before
    assert db.query(StayPayment).filter_by(tenant_id=tenant.id).count() == 0
    assert db.query(AuditEvent).filter_by(tenant_id=tenant.id, action="quote.payment_received").count() == 1
    q.after.assert_not_called()
    q.notify.assert_called_once()


# ── Booking template sends ───────────────────────────────────────────────────

def test_send_skipped_and_audited_when_template_not_approved(db, tenant_and_user, q):
    stay = _setup(db, tenant_and_user, approve=False)
    tid = tenant_and_user["tenant"].id
    res = wa_booking_messages.send_booking_template(db, tid, stay, wa_booking_pack.PAYMENT_RECEIVED, ["a", "b", "c", "d"],
                                                    event="test", document={"key": f"{tid}/invoices/x.pdf"})
    assert res == {"status": "skipped", "reason": "template not approved", "message_id": None}
    assert db.query(Message).filter_by(tenant_id=tid).count() == 0 and not q.send.called
    ev = db.query(AuditEvent).filter_by(tenant_id=tid, action="booking.message_not_sent").one()
    assert ev.payload["template"] == wa_booking_pack.PAYMENT_RECEIVED and ev.target_id == stay.id


def test_bad_phone_is_skipped_without_the_number_in_the_reason(db, tenant_and_user, q):
    stay = _setup(db, tenant_and_user)
    stay.guest.phone = "+91123"
    db.commit()
    res = wa_booking_messages.send_booking_template(db, stay.tenant_id, stay, wa_booking_pack.BALANCE_DUE, ["a", "b", "c", "d"],
                                                    event="x", url_suffix="i/A")
    assert res["status"] == "skipped" and "+91123" not in res["reason"] and not q.send.called


def test_same_booking_event_is_never_sent_twice(db, tenant_and_user, q):
    stay = _setup(db, tenant_and_user)
    tid = tenant_and_user["tenant"].id
    args = (db, tid, stay, wa_booking_pack.PAYMENT_RECEIVED, ["Kiran", "₹1", "#AB", "ok"])
    kw = {"event": "paid:abc", "document": {"key": f"{tid}/invoices/x.pdf", "filename": "Receipt.pdf"}}
    assert wa_booking_messages.send_booking_template(*args, **kw)["status"] == "queued"
    assert wa_booking_messages.send_booking_template(*args, **kw)["status"] == "duplicate"
    assert wa_booking_messages.send_booking_template(*args, **{**kw, "event": "paid:def"})["status"] == "queued"
    assert q.send.call_count == 2
    keys = {m.idempotency_key for m in db.query(Message).filter_by(tenant_id=tid)}
    assert keys == {f"bk:{stay.id}:paid:abc", f"bk:{stay.id}:paid:def"}


def test_payment_link_send_whatsapp_uses_button_suffix_or_says_why(client, db, tenant_and_user, q):
    stay = _setup(db, tenant_and_user, approve=False)
    h = _h(tenant_and_user)
    fake = lambda key_id, key_secret, **kw: {"id": f"plink_{uuid.uuid4().hex[:8]}", "short_url": "https://rzp.io/i/Zx9"}  # noqa: E731
    with patch("app.adapters.payments.razorpay.create_payment_link", side_effect=fake):
        r = client.post(f"/api/v1/bookings/{stay.id}/payment-links", json={"send_whatsapp": True}, headers=h).json()
        assert r["short_url"] == "https://rzp.io/i/Zx9" and r["whatsapp"] == {"status": "skipped", "reason": "template not approved", "via": "template"}
        _approve(db, tenant_and_user["tenant"].id, names=[wa_booking_pack.BALANCE_DUE])
        r = client.post(f"/api/v1/bookings/{stay.id}/payment-links", json={"send_whatsapp": True, "amount": 5000}, headers=h).json()
        assert r["whatsapp"]["status"] == "queued"
        plain = client.post(f"/api/v1/bookings/{stay.id}/payment-links", json={}, headers=h).json()
        assert "whatsapp" not in plain
    msg = db.query(Message).filter_by(tenant_id=tenant_and_user["tenant"].id).one()
    assert msg.channel_metadata["button_params"] == {"0": "i/Zx9"} and "₹5,000" in msg.body
    rows = client.get(f"/api/v1/bookings/{stay.id}/booking-messages", headers=h).json()
    assert rows["messages"][0]["template"] == wa_booking_pack.BALANCE_DUE and rows["templates"][wa_booking_pack.BALANCE_DUE] == "approved"


def test_booking_messages_endpoint_forbidden_and_cross_tenant(client, db, tenant_and_user):
    from app.core.security import create_access_token
    from app.models.tenant import Tenant
    from app.models.user import User, UserRole
    stay = _setup(db, tenant_and_user, approve=False)
    mk = User(id=str(uuid.uuid4()), tenant_id=stay.tenant_id, name="M", email=f"m-{uuid.uuid4().hex[:6]}@t.com", hashed_password="x",
              role=UserRole.MARKETING, is_active=True)
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add_all([mk, other])
    db.flush()
    owner2 = User(id=str(uuid.uuid4()), tenant_id=other.id, name="O", email=f"o-{uuid.uuid4().hex[:6]}@t.com", hashed_password="x",
                  role=UserRole.OWNER, is_active=True)
    db.add(owner2)
    db.commit()
    from tests.conftest import seed_capabilities
    seed_capabilities(db, other.id)
    tok = lambda u: {"Authorization": "Bearer " + create_access_token({"sub": u.id, "tenant_id": u.tenant_id, "role": u.role.value})}  # noqa: E731
    assert client.get(f"/api/v1/bookings/{stay.id}/booking-messages", headers=tok(mk)).status_code == 403
    assert client.get(f"/api/v1/bookings/{stay.id}/booking-messages", headers=tok(owner2)).status_code == 404


# ── Balance reminders ────────────────────────────────────────────────────────

def test_balance_reminders_off_by_default_then_once_per_instalment(db, tenant_and_user, q):
    stay = _setup(db, tenant_and_user)
    tenant = tenant_and_user["tenant"]
    today = date.today()
    db.add_all([
        StayInstalment(tenant_id=tenant.id, stay_id=stay.id, label="Advance", amount=8000, due_date=today - timedelta(days=5)),
        StayInstalment(tenant_id=tenant.id, stay_id=stay.id, label="Balance", amount=12000, due_date=today + timedelta(days=3)),
    ])
    db.add(StayPayment(tenant_id=tenant.id, stay_id=stay.id, amount=8000, method="upi", paid_on=today))
    db.commit()
    made = []

    def fake(key_id, key_secret, **kw):
        made.append(kw["amount_inr"])
        return {"id": f"plink_{len(made)}", "short_url": f"https://rzp.io/i/R{len(made)}"}

    with patch("app.adapters.payments.razorpay.create_payment_link", side_effect=fake):
        assert balance_reminder_service.run_for_tenant(db, tenant, today) == {"status": "off"}
        tenant.brand_config = {**tenant.brand_config, "payments": {"auto_balance_reminder": True}}
        db.commit()
        assert balance_reminder_service.run_for_tenant(db, tenant, today)["sent"] == 1
        assert balance_reminder_service.run_for_tenant(db, tenant, today)["sent"] == 0              # same day re-run
        assert balance_reminder_service.run_for_tenant(db, tenant, today + timedelta(days=1))["sent"] == 0
    assert made == [12000]                                                                          # one link, for what is left
    assert q.send.call_count == 1 and q.send.call_args.kwargs["template_name"] == wa_booking_pack.BALANCE_DUE


def test_balance_reminder_task_skips_tenants_that_did_not_opt_in(db, tenant_and_user, q, monkeypatch):
    from app.workers.tasks import invoice_tasks
    _setup(db, tenant_and_user)
    monkeypatch.setattr(invoice_tasks, "SessionLocal", lambda: db)
    with patch("app.services.balance_reminder_service.run_for_tenant") as run:
        assert invoice_tasks.balance_reminders.run() == {}
    run.assert_not_called()
