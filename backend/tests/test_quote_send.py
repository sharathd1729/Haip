"""POST /quotes/{id}/send: a Razorpay link per option + the WhatsApp quote (queued), and the task that renders the PDF and sends it.

Per endpoint: happy path, a role without quotes.write (403), another tenant (404); every refusal; resending reuses live links;
the task sends ratha_quote_payment_v1 once with the PDF and the primary link's rzp.io ending, and the fallback link only while
the guest's 24-hour window is open. No real Razorpay, Meta or storage: all mocked.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from itertools import count
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.api.v1.endpoints.messaging import TemplateCategory, TemplateStatus, WATemplate  # noqa: E402
from app.core.encryption import encrypt_credentials  # noqa: E402
from app.models.audit_event import AuditEvent  # noqa: E402
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.inquiry_360 import InquiryQuote  # noqa: E402
from app.models.integration import Integration  # noqa: E402
from app.models.stay_finance import StayPaymentLink  # noqa: E402
from app.models.user import UserRole  # noqa: E402
from app.services import quote_pdf, quote_send_service, wa_booking_pack  # noqa: E402
from tests.test_business_data import _tenant  # noqa: E402
from tests.test_increment1_defect_specs import _h, _user  # noqa: E402
from tests.test_quote_builder_pricing import ratha  # noqa: E402
from tests.test_quotes_api import API, coorg_option, day_option, lead  # noqa: E402

WEBHOOK_SECRET = "whsec_quote_123"


@pytest.fixture()
def w(db):
    w = ratha(db)
    w.res = _user(db, w.t.id, UserRole.RESERVATIONS)
    w.foh = _user(db, w.t.id, UserRole.FOH)
    return w


def connect_razorpay(db, tenant_id):
    db.add(Integration(tenant_id=tenant_id, kind="razorpay", status="active", config={},
                       credentials_kms_blob=encrypt_credentials({"key_id": "rzp_test_k", "key_secret": "s", "webhook_secret": WEBHOOK_SECRET})))
    db.commit()


def approve_quote_template(db, tenant_id):
    t = wa_booking_pack.BY_NAME[wa_booking_pack.QUOTE_PAYMENT]
    db.add(WATemplate(tenant_id=tenant_id, name=t["name"], language="en", category=TemplateCategory.UTILITY,
                      status=TemplateStatus.APPROVED, components=t["components"]))
    db.commit()


@pytest.fixture()
def rzp():
    """Razorpay, the Celery queue, WhatsApp sends and storage: all mocked."""
    n = count(1)

    def make(*args, **kw):
        i = next(n)
        return {"id": f"plink_{i}", "short_url": f"https://rzp.io/i/Lnk{i}"}
    with patch("app.adapters.payments.razorpay.create_payment_link", side_effect=make) as create, \
         patch("app.workers.tasks.quote_tasks.send_with_links.delay") as task, \
         patch("app.workers.tasks.send_whatsapp.send_whatsapp_template.delay") as send_t, \
         patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay") as send_text, \
         patch("app.services.media_storage.upload_quote_pdf", side_effect=lambda tid, qid, pdf: f"{tid}/quotes/{qid}.pdf") as up:
        yield type("R", (), {"create": create, "task": task, "send_t": send_t, "send_text": send_text, "upload": up})


def saved_quote(client, db, w, *, stay_check="confirmed", fallback=True, user=None, **primary):
    inq = lead(db, w.t.id, assigned_to=None)
    body = {"inquiry_id": inq.id, "primary": coorg_option(**primary), "stay_check": stay_check}
    if fallback:
        body["fallback"] = day_option()
    res = client.post(API, json=body, headers=_h(user or w.owner))
    assert res.status_code == 201, res.text
    return inq, res.json()["quotes"]


def ready(client, db, w, **kw):
    connect_razorpay(db, w.t.id)
    approve_quote_template(db, w.t.id)
    return saved_quote(client, db, w, **kw)


# ─── POST /quotes/{id}/send ───────────────────────────────────────────────────────────────────────────────

def test_send_makes_a_link_per_option_and_queues_the_message(client, db, w, rzp):
    inq, (p, f) = ready(client, db, w)
    res = client.post(f"{API}/{p['id']}/send", headers=_h(w.res))
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["message"]["status"] == "queued"
    assert rzp.create.call_count == 2
    first, second = (c.kwargs for c in rzp.create.call_args_list)
    assert first["amount_inr"] == 44940 and second["amount_inr"] == float(f["snapshot"]["advance"])
    assert first["notes"] == {"haip_tenant_id": w.t.id, "haip_inquiry_quote_id": p["id"]}
    assert second["notes"]["haip_inquiry_quote_id"] == f["id"]
    valid_until = datetime.fromisoformat(p["valid_until"])
    assert abs(first["expire_by"] - int(valid_until.timestamp())) <= 1
    links = db.query(StayPaymentLink).filter_by(tenant_id=w.t.id).order_by(StayPaymentLink.created_at).all()
    assert [(lk.inquiry_quote_id, lk.stay_id, lk.status) for lk in links] == [(p["id"], None, "created"), (f["id"], None, "created")]
    rzp.task.assert_called_once_with(tenant_id=w.t.id, quote_id=p["id"], link_id=links[0].id)
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="quote.sent").count() == 1
    opts = out["journey"]["options"]
    assert [o["link"]["short_url"] for o in opts] == ["https://rzp.io/i/Lnk1", "https://rzp.io/i/Lnk2"]
    assert out["journey"]["message"]["status"] == "sending" and out["journey"]["polling"] is True

    got = client.get(f"{API}/{p['id']}", headers=_h(w.owner)).json()
    assert got["payment_link"]["status"] == "created" and got["send"]["quote_number"].startswith("Q-")
    assert got["send_readiness"]["can_send"] is True
    listed = client.get(API, params={"inquiry_id": inq.id}, headers=_h(w.owner)).json()
    assert {q["payment_link"]["short_url"] for q in listed} == {"https://rzp.io/i/Lnk1", "https://rzp.io/i/Lnk2"}


def test_sending_again_reuses_the_live_links(client, db, w, rzp):
    _, (p, _f) = ready(client, db, w)
    client.post(f"{API}/{p['id']}/send", headers=_h(w.owner))
    again = client.post(f"{API}/{p['id']}/send", headers=_h(w.owner))
    assert again.status_code == 200 and rzp.create.call_count == 2
    assert db.query(StayPaymentLink).filter_by(tenant_id=w.t.id).count() == 2
    # once the message went out, a resend does not queue another one
    quote_send_service.deliver(db, w.t.id, p["id"], rzp.task.call_args.kwargs["link_id"])
    rzp.task.reset_mock()
    third = client.post(f"{API}/{p['id']}/send", headers=_h(w.owner)).json()
    assert third["message"]["status"] == "already_sent" and not rzp.task.called and rzp.create.call_count == 2


def test_an_expired_link_is_replaced(client, db, w, rzp):
    _, (p,) = ready(client, db, w, fallback=False)
    client.post(f"{API}/{p['id']}/send", headers=_h(w.owner))
    link = db.query(StayPaymentLink).filter_by(tenant_id=w.t.id).one()
    link.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    client.post(f"{API}/{p['id']}/send", headers=_h(w.owner))
    assert rzp.create.call_count == 2 and db.query(StayPaymentLink).filter_by(tenant_id=w.t.id).count() == 2


def test_send_needs_quotes_write(client, db, w, rzp):
    _, (p, _f) = ready(client, db, w)
    assert client.post(f"{API}/{p['id']}/send", headers=_h(w.foh)).status_code == 403
    assert client.post(f"{API}/{p['id']}/send", headers=_h(w.ro)).status_code == 403
    assert not rzp.create.called


def test_another_tenants_quote_is_not_found(client, db, w, rzp):
    _, (p, _f) = ready(client, db, w)
    other = _tenant(db)
    res = client.post(f"{API}/{p['id']}/send", headers=_h(_user(db, other.id, UserRole.OWNER)))
    assert res.status_code == 404 and not rzp.create.called


def _refused(client, w, quote_id, code, status=422):
    res = client.post(f"{API}/{quote_id}/send", headers=_h(w.owner))
    assert res.status_code == status, res.text
    assert res.json()["detail"]["code"] == code
    return res.json()["detail"]["message"]


def test_refuses_an_unconfirmed_overnight_stay(client, db, w, rzp):
    _, (p, _f) = ready(client, db, w, stay_check="checking")
    assert "overnight stay" in _refused(client, w, p["id"], "stay_not_confirmed")
    assert not rzp.create.called


def test_refuses_without_razorpay(client, db, w, rzp):
    approve_quote_template(db, w.t.id)
    _, (p, _f) = saved_quote(client, db, w)
    assert "Razorpay is not connected" in _refused(client, w, p["id"], "razorpay_not_connected")
    assert not rzp.create.called


def test_refuses_a_guest_without_a_number(client, db, w, rzp):
    inq, (p, _f) = ready(client, db, w)
    guest = db.query(Guest).filter_by(id=inq.guest_id).one()
    guest.phone = ""
    db.commit()
    _refused(client, w, p["id"], "no_phone")
    assert not rzp.create.called


def test_refuses_a_superseded_or_expired_quote(client, db, w, rzp):
    inq, (p, _f) = ready(client, db, w)
    newer = client.post(API, json={"inquiry_id": inq.id, "primary": coorg_option(adults=4, children=0), "stay_check": "confirmed"},
                        headers=_h(w.owner))
    assert newer.status_code == 201
    assert "superseded" in _refused(client, w, p["id"], "quote_not_valid", 409)
    fresh = newer.json()["quotes"][0]
    row = db.query(InquiryQuote).filter_by(id=fresh["id"]).one()
    row.valid_until = datetime.now(timezone.utc) - timedelta(hours=1)
    db.commit()
    assert "expired" in _refused(client, w, fresh["id"], "quote_not_valid", 409)
    assert not rzp.create.called


def test_template_not_approved_still_makes_the_links_but_sends_nothing(client, db, w, rzp):
    connect_razorpay(db, w.t.id)
    _, (p, _f) = saved_quote(client, db, w)
    readiness = client.get(f"{API}/{p['id']}", headers=_h(w.owner)).json()["send_readiness"]
    assert readiness["can_send"] is True and readiness["warnings"][0]["code"] == "template_not_approved"
    res = client.post(f"{API}/{p['id']}/send", headers=_h(w.owner))
    assert res.status_code == 200
    out = res.json()
    assert out["message"]["status"] == "not_sent" and out["message"]["code"] == "template_not_approved"
    assert len([o for o in out["journey"]["options"] if o["link"]]) == 2 and not rzp.task.called
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="quote.message_not_sent").count() == 1


def test_catalog_says_what_sending_needs(client, db, w):
    setup = client.get(f"{API}/catalog", headers=_h(w.res)).json()["send_setup"]
    assert setup == {"razorpay_connected": False, "template_status": None}
    connect_razorpay(db, w.t.id)
    approve_quote_template(db, w.t.id)
    assert client.get(f"{API}/catalog", headers=_h(w.res)).json()["send_setup"] == {"razorpay_connected": True, "template_status": "approved"}


# ─── the task: PDF + template + fallback ─────────────────────────────────────────────────────────────────

def _deliver(db, w, rzp, p):
    return quote_send_service.deliver(db, w.t.id, p["id"], rzp.task.call_args.kwargs["link_id"])


def test_deliver_sends_the_template_with_pdf_and_primary_link_once(client, db, w, rzp):
    inq, (p, _f) = ready(client, db, w)
    client.post(f"{API}/{p['id']}/send", headers=_h(w.owner))
    res = _deliver(db, w, rzp, p)
    assert res["status"] == "queued" and res["fallback"] == "window_closed"
    assert rzp.upload.call_args.args[2].startswith(b"%PDF")
    msg = db.query(Message).filter_by(tenant_id=w.t.id).one()
    meta = msg.channel_metadata
    assert meta["template_name"] == wa_booking_pack.QUOTE_PAYMENT and meta["button_params"] == {"0": "i/Lnk1"}
    assert meta["document"]["key"] == f"{w.t.id}/quotes/{p['id']}.pdf" and meta["document"]["filename"].startswith("Ratha quote Q-")
    v = rzp.send_t.call_args.kwargs["variables"]
    assert v[0] == "Kiran" and v[1] == "Coorg, stay in Virajpet (Coorg 48-hour Retreat)" and v[4] == "6" and v[5] == "₹89,880" and v[6] == "₹44,940"
    assert len(v) == 8 and "Rs." not in msg.body
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="quote.fallback_link_not_sent").count() == 1
    assert _deliver(db, w, rzp, p)["status"] == "duplicate" and rzp.send_t.call_count == 1 and rzp.upload.call_count == 1
    journey = client.get(f"{API}/{p['id']}", headers=_h(w.owner)).json()["send"]
    assert journey["message"]["status"] == "queued" and journey["fallback_message"] is None


def test_deliver_sends_the_fallback_link_while_the_window_is_open(client, db, w, rzp):
    inq, (p, _f) = ready(client, db, w)
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=w.t.id, guest_id=inq.guest_id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv)
    db.add(Message(id=str(uuid.uuid4()), tenant_id=w.t.id, conversation_id=conv.id, direction=MessageDirection.INBOUND,
                   channel=ChannelType.WHATSAPP, body="Hi, price please?"))
    db.commit()
    client.post(f"{API}/{p['id']}/send", headers=_h(w.owner))
    assert _deliver(db, w, rzp, p)["fallback"] == "queued"
    text = db.query(Message).filter(Message.tenant_id == w.t.id, Message.channel_metadata.isnot(None),
                                    Message.direction == MessageDirection.OUTBOUND).all()
    fb = [m for m in text if (m.channel_metadata or {}).get("quote_event", "").startswith("fb:")]
    assert len(fb) == 1 and "https://rzp.io/i/Lnk2" in fb[0].body and fb[0].conversation_id == conv.id
    rzp.send_text.assert_called_once_with(message_id=fb[0].id, tenant_id=w.t.id)
    _deliver(db, w, rzp, p)
    assert rzp.send_text.call_count == 1


def test_quote_pdf_renders_both_options():
    snap = {"package_name": "Coorg 48-hour Retreat", "destination": {"name": "Coorg"}, "inputs": {"check_in": "2026-11-01",
            "check_out": "2026-11-03", "adults": 5, "children": 1},
            "lines": [{"label": "Coorg 48-hour Retreat", "amount": "70000.00", "detail": "48 hours"}, {"label": "Discount", "amount": "-500"}],
            "taxable": "80250.00", "gst_percent": "12", "gst": "9630", "total": "89880.00", "advance_percent": "50", "advance": "44940",
            "at_actuals": ["Tolls and parking"], "inclusions": ["Driver"]}
    pdf = quote_pdf.render(number="Q-1A2B3C4D", issued_on=datetime(2026, 10, 18).date(), valid_until="2026-10-21",
                           seller={"legal_name": "Ratha Journeys LLP", "gstin": "29AAGCB7383J1Z4", "address": "Bengaluru"},
                           buyer={"name": "Kiran <b>Rao</b>", "phone": "+919800000000"},
                           options=[{"title": "Option 1", "snapshot": snap, "guests": 6, "pay_url": "https://rzp.io/i/x"},
                                    {"title": "Option 2 (fallback)", "snapshot": snap, "guests": 6}])
    assert pdf.startswith(b"%PDF") and len(pdf) > 1500
