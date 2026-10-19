"""/quote-calculator: setup, price (no writes), save + send / copy / save only, the owner's OK for a lowered price, the "Send to"
picker and "Add as new lead", the prefill context, and settings.

Per endpoint: happy path, a role without quotes.write (403) and another tenant (404 / nothing returned). Razorpay, WhatsApp sends,
Celery and pushes are mocked: nothing leaves the test.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.audit_event import AuditEvent
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity
from app.models.inquiry import Inquiry, InquirySource, InquiryStage
from app.models.inquiry_360 import InquiryQuote
from app.models.pipeline_stage import PipelineStage
from app.models.task import Task
from app.models.user import UserRole
from app.services.pipeline_stage_service import seed_default_pipeline_stages
from tests.test_business_data import TODAY, _tenant
from tests.test_increment1_defect_specs import _h, _user
from tests.test_quote_builder_pricing import ratha
from tests.test_quote_send import approve_quote_template, connect_razorpay, rzp  # noqa: F401  (fixture)

API = "/api/v1/quote-calculator"
START = (TODAY + timedelta(days=12)).isoformat()


@pytest.fixture()
def w(db):
    w = ratha(db)
    w.res = _user(db, w.t.id, UserRole.RESERVATIONS)
    w.foh = _user(db, w.t.id, UserRole.FOH)
    w.stages = {s.key: s for s in seed_default_pipeline_stages(db, w.t.id)}
    db.commit()
    return w


@pytest.fixture(autouse=True)
def push():
    with patch("app.workers.tasks.invoice_tasks.notify_staff.delay") as p:
        yield p


def person(db, tenant_id, name="Kiran Reddy", phone=None):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, phone=phone or f"+9198{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    db.commit()
    return g


def lead(db, w, stage="general_enquiry", guest=None, assigned_to=None, legacy=False):
    g = guest or person(db, w.t.id)
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=w.t.id, guest_id=g.id, source=InquirySource.WA_DIRECT, assigned_to=assigned_to,
                  stage=InquiryStage.NEW, stage_id=None if legacy else w.stages[stage].id)
    db.add(inq)
    db.commit()
    return inq


def body(**kw):
    b = {"mode": "fixed", "package_key": "coorg-48", "start_date": START, "days": 2, "guests": 5, "gst_percent": "18",
         "prices_include_gst": True, "payment_link": False}
    b.update(kw)
    return b


def save(client, user, inq=None, **kw):
    extra = {"inquiry_id": inq.id} if inq is not None and "guest_id" not in kw else {}
    return client.post(f"{API}/quotes", json=body(**{**extra, **kw}), headers=_h(user))


def inbound(db, tenant_id, guest_id):
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest_id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(c)
    db.flush()
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tenant_id, conversation_id=c.id, direction=MessageDirection.INBOUND,
                   channel=ChannelType.WHATSAPP, body="price for coorg?", created_at=datetime.now(timezone.utc) - timedelta(minutes=5)))
    db.commit()


# ─── setup / price ────────────────────────────────────────────────────────────────────────────────────────

def test_setup_lists_published_route_packages_and_counts_the_rest(client, db, w):
    from app.services import business_data_service as bds
    from tests.test_quote_builder_pricing import day_rate
    bds.create_draft(db, w.t.id, "package", "draft-only", day_rate(name="Draft only"), w.owner.id)
    db.commit()
    res = client.get(f"{API}/setup", headers=_h(w.res))
    assert res.status_code == 200, res.text
    out = res.json()
    names = [p["name"] for p in out["packages"]]
    assert "Coorg 48-hour Retreat" in names and "Draft only" not in names and out["unpublished"] == 1
    assert out["settings"]["gst_percent"] == "18" and out["settings"]["prices_include_gst"] is True
    assert out["settings"]["advance_percent"] == "50.00" and out["custom"]["rate_per_day"] == "25000.00"
    assert out["discount_options"] == ["0", "2.5", "5", "7.5", "10"] and out["permissions"]["privileged"] is False
    assert client.get(f"{API}/setup", headers=_h(w.foh)).status_code == 403


def test_price_writes_nothing_and_returns_the_message(client, db, w):
    inq = lead(db, w)
    before = (db.query(InquiryQuote).count(), db.query(AuditEvent).count(), db.query(Task).count())
    res = client.post(f"{API}/price", json=body(inquiry_id=inq.id, payment_link=True), headers=_h(w.res))
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["ok"] and out["total"] == "70000.00" and out["gst"] == "10678" and out["advance"] == "35000"
    assert out["message_text"].startswith("Namaskara Kiran,") and "Pay the advance here: rzp.io/…" in out["message_text"]
    assert {v["property_name"]: v["status"] for v in out["availability"]} == {"Ratha 1": "available", "Ratha 2": "available"}
    assert (db.query(InquiryQuote).count(), db.query(AuditEvent).count(), db.query(Task).count()) == before
    assert client.post(f"{API}/price", json=body(), headers=_h(w.foh)).status_code == 403


# ─── save, copy, stage ────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("stage,label", [("general_enquiry", "General Enquiry"), ("rnr", "RNR"), ("unqualified", "Unqualified")])
def test_copy_saves_the_quote_moves_a_not_engaged_lead_to_active_and_sets_the_follow_up(client, db, w, stage, label):
    inq = lead(db, w, stage)
    with patch("app.services.inquiry_service._notify_stage_hooks") as hooks:
        res = save(client, w.res, inq, action="copy")
    assert res.status_code == 201, res.text
    out = res.json()
    assert out["how"] == "copied" and out["stage"] == {"from": label, "to": "Active", "moved": True}
    assert out["message_text"].startswith("Namaskara Kiran,") and "Pay the advance" not in out["message_text"]
    hooks.assert_called_once()
    db.expire_all()
    row = db.query(InquiryQuote).filter_by(id=out["quote_id"]).one()
    assert (row.status, row.shared_via, row.snapshot["kind"], float(row.amount)) == ("issued", "copied", "calculator", 70000)
    assert db.query(Inquiry).filter_by(id=inq.id).one().stage_id == w.stages["active"].id
    task = db.query(Task).filter(Task.inquiry_id == inq.id, Task.title.like("Follow up on the quote%")).one()
    assert task.due_date.date() == row.valid_until.date() and out["follow_up_at"]
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="quote.copied").count() == 1
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="inquiry.stage_changed").count() == 1


def test_legacy_stage_path_also_moves_and_fires_hooks(client, db, w):
    inq = lead(db, w, legacy=True)
    with patch("app.services.inquiry_service._notify_stage_hooks") as hooks:
        out = save(client, w.res, inq, action="copy").json()
    assert out["stage"]["moved"] is True and hooks.called
    db.expire_all()
    assert db.query(Inquiry).filter_by(id=inq.id).one().stage == InquiryStage.RESPONDING


@pytest.mark.parametrize("stage", ["active", "unsuitable", "collaboration_engagement"])
def test_a_valid_lead_is_never_moved(client, db, w, stage):
    inq = lead(db, w, stage)
    out = save(client, w.res, inq, action="copy").json()
    assert out["stage"]["moved"] is False
    db.expire_all()
    assert db.query(Inquiry).filter_by(id=inq.id).one().stage_id == w.stages[stage].id


def test_save_only_does_not_move_the_stage(client, db, w):
    inq = lead(db, w, "rnr")
    out = save(client, w.res, inq, action="save").json()
    assert out["how"] == "saved" and out["stage"]["moved"] is False
    db.expire_all()
    assert db.query(InquiryQuote).filter_by(id=out["quote_id"]).one().shared_via is None


def test_saving_the_same_quote_twice_returns_it_and_a_change_supersedes(client, db, w):
    inq = lead(db, w)
    a = save(client, w.res, inq).json()
    assert save(client, w.res, inq).json()["quote_id"] == a["quote_id"]
    b = save(client, w.res, inq, guests=7).json()
    db.expire_all()
    assert b["quote_id"] != a["quote_id"] and db.query(InquiryQuote).filter_by(id=a["quote_id"]).one().status == "superseded"


def test_a_closed_lead_gets_a_new_lead_for_this_trip(client, db, w):
    sold = lead(db, w, "sold")
    out = save(client, w.res, sold, action="copy").json()
    assert out["lead_created"] is True and out["lead"]["inquiry_id"] != sold.id
    db.expire_all()
    new = db.query(Inquiry).filter_by(id=out["lead"]["inquiry_id"]).one()
    assert new.guest_id == sold.guest_id and new.assigned_to == w.res.id
    assert db.query(Inquiry).filter_by(id=sold.id).one().stage_id == w.stages["sold"].id
    again = save(client, w.res, guest_id=sold.guest_id).json()             # the person now has an open lead: it is used
    assert again["lead"]["inquiry_id"] == new.id and again["lead_created"] is False


def test_another_tenants_lead_or_quote_is_not_found(client, db, w):
    inq = lead(db, w)
    quote = save(client, w.res, inq).json()
    other = _user(db, _tenant(db).id, UserRole.OWNER)
    assert save(client, other, inq).status_code == 404
    assert client.get(f"{API}/quotes/{quote['quote_id']}", headers=_h(other)).status_code == 404
    assert client.post(f"{API}/quotes/{quote['quote_id']}/approve", headers=_h(other)).status_code == 404
    assert client.post(f"{API}/quotes/{quote['quote_id']}/share", json={"action": "copy"}, headers=_h(other)).status_code == 404
    assert save(client, w.foh, inq).status_code == 403


# ─── price override and the owner's OK ────────────────────────────────────────────────────────────────────

def test_more_than_ten_percent_off_waits_for_the_owner(client, db, w, push):
    inq = lead(db, w)
    out = save(client, w.res, inq, action="send", override={"price": "60000", "reason": "repeat guest"}).json()
    assert out["how"] == "pending_approval" and out["status"] == "pending_approval" and out["approval"]["needed"]
    db.expire_all()
    row = db.query(InquiryQuote).filter_by(id=out["quote_id"]).one()
    assert row.shared_via is None and row.snapshot["override"]["reason"] == "repeat guest"
    assert row.snapshot["suggested_total"] == "70000.00" and float(row.amount) == 60000
    task = db.query(Task).filter(Task.inquiry_id == inq.id, Task.title.like("Approve quote%")).one()
    assert task.assigned_to == w.owner.id and push.called
    assert db.query(Inquiry).filter_by(id=inq.id).one().stage_id == w.stages["general_enquiry"].id     # nothing reached the guest
    blocked = client.post(f"{API}/quotes/{row.id}/share", json={"action": "copy"}, headers=_h(w.res))
    assert blocked.status_code == 409 and "owner" in blocked.json()["detail"]["message"]
    assert client.post(f"{API}/quotes/{row.id}/approve", headers=_h(w.res)).status_code == 403

    ok = client.post(f"{API}/quotes/{row.id}/approve", headers=_h(w.mgr))
    assert ok.status_code == 200, ok.text and ok.json()["status"] == "issued"
    db.expire_all()
    row = db.query(InquiryQuote).filter_by(id=row.id).one()
    assert (row.status, row.approved_by) == ("issued", w.mgr.id)
    assert db.query(Task).filter_by(id=task.id).one().is_done is True
    assert db.query(AuditEvent).filter_by(tenant_id=w.t.id, action="quote.approved").count() == 1
    assert client.post(f"{API}/quotes/{row.id}/approve", headers=_h(w.mgr)).status_code == 409
    shared = client.post(f"{API}/quotes/{row.id}/share", json={"action": "copy"}, headers=_h(w.res)).json()
    assert shared["how"] == "copied" and "Your price ₹60,000" in shared["message_text"] and "Usual price ~₹70,000~" in shared["message_text"]


def test_no_self_approval_except_the_owner(client, db, w):
    inq = lead(db, w)
    out = save(client, w.res, inq, override={"price": "60000"}).json()
    row = db.query(InquiryQuote).filter_by(id=out["quote_id"]).one()
    row.created_by = w.mgr.id
    db.commit()
    assert client.post(f"{API}/quotes/{row.id}/approve", headers=_h(w.mgr)).json()["detail"]["code"] == "self_approval"
    row.created_by = w.owner.id
    db.commit()
    assert client.post(f"{API}/quotes/{row.id}/approve", headers=_h(w.owner)).status_code == 200


def test_small_overrides_and_privileged_users_need_no_approval(client, db, w):
    inq = lead(db, w)
    assert save(client, w.res, inq, override={"price": "64000"}).json()["status"] == "issued"          # 8.6% below
    assert save(client, w.mgr, inq, override={"price": "50000"}).json()["status"] == "issued"          # a manager's own call
    assert save(client, w.res, inq, override={"price": "90000"}).json()["status"] == "issued"          # above


# ─── send on WhatsApp ─────────────────────────────────────────────────────────────────────────────────────

def test_send_in_the_24h_window_is_the_exact_preview_text_with_the_link(client, db, w, rzp):
    connect_razorpay(db, w.t.id)
    inq = lead(db, w)
    inbound(db, w.t.id, inq.guest_id)
    preview = client.post(f"{API}/price", json=body(inquiry_id=inq.id, payment_link=True), headers=_h(w.res)).json()
    out = save(client, w.res, inq, action="send", payment_link=True).json()
    assert out["how"] == "sent" and out["message"]["status"] == "queued" and out["message"]["channel"] == "text"
    assert out["payment_link"] == "https://rzp.io/i/Lnk1" and rzp.create.call_args.kwargs["amount_inr"] == 35000
    sent = db.query(Message).filter_by(tenant_id=w.t.id, direction=MessageDirection.OUTBOUND).one()
    assert sent.body == preview["message_text"].replace("rzp.io/…", "https://rzp.io/i/Lnk1")
    assert rzp.send_text.called and out["stage"]["moved"] is True
    again = client.post(f"{API}/quotes/{out['quote_id']}/share", json={"action": "send"}, headers=_h(w.res)).json()
    assert again["message"]["status"] == "already_sent" and rzp.create.call_count == 1


def test_send_outside_the_window_uses_the_template_or_says_why(client, db, w, rzp):
    connect_razorpay(db, w.t.id)
    inq = lead(db, w)
    out = save(client, w.res, inq, action="send", payment_link=True).json()
    assert out["how"] == "saved" and out["message"]["code"] == "template_not_approved" and out["stage"]["moved"] is False
    assert not rzp.create.called
    no_link = save(client, w.res, inq, action="send", payment_link=False).json()
    assert no_link["message"]["code"] == "needs_template_link"
    approve_quote_template(db, w.t.id)
    ok = client.post(f"{API}/quotes/{out['quote_id']}/share", json={"action": "send"}, headers=_h(w.res))
    assert ok.status_code == 409          # the no-link save superseded it; send the newest one
    newest = save(client, w.res, inq, action="send", payment_link=True).json()
    assert newest["message"]["status"] == "queued" and newest["message"]["channel"] == "template" and rzp.task.called


# ─── Send to: search, add a lead, prefill ─────────────────────────────────────────────────────────────────

def test_search_open_leads_first_and_offer_a_new_number(client, db, w):
    g = person(db, w.t.id, "Meera Shah")
    lead(db, w, "sold", guest=g)
    lead(db, w, "active", guest=g)
    rows = client.get(f"{API}/leads", params={"q": "meera"}, headers=_h(w.res)).json()["results"]
    assert [r["kind"] for r in rows] == ["lead", "new_trip"]
    unknown = client.get(f"{API}/leads", params={"q": "98450 12345"}, headers=_h(w.res)).json()
    assert unknown["results"] == [] and unknown["add"]["phone"] == "+919845012345" and unknown["add"]["known"] is False
    other = _user(db, _tenant(db).id, UserRole.OWNER)
    assert client.get(f"{API}/leads", params={"q": "meera"}, headers=_h(other)).json()["results"] == []


def test_add_lead_reuses_a_person_known_only_by_phone_never_a_duplicate(client, db, w):
    mirrored = person(db, w.t.id, "Rahul", phone="+919845012345")         # a mirrored WhatsApp chat: number on the row, no signal
    guests = db.query(Guest).filter_by(tenant_id=w.t.id).count()
    res = client.post(f"{API}/leads", json={"phone": "98450 12345", "source": "phone_call"}, headers=_h(w.res))
    assert res.status_code == 201, res.text
    out = res.json()
    assert out["guest_id"] == mirrored.id and out["matched_existing"] is True and out["created"] is True
    db.expire_all()
    assert db.query(Guest).filter_by(tenant_id=w.t.id).count() == guests
    assert db.query(GuestIdentity).filter_by(tenant_id=w.t.id, guest_id=mirrored.id, identity_value="+919845012345").count() == 1
    assert db.query(Guest).filter_by(id=mirrored.id).one().lead_identified_at is not None
    inq = db.query(Inquiry).filter_by(id=out["inquiry_id"]).one()
    assert inq.assigned_to == w.res.id and inq.source == InquirySource.ORGANIC_CALL
    second = client.post(f"{API}/leads", json={"phone": "+91 98450 12345", "source": "whatsapp"}, headers=_h(w.res)).json()
    assert second["inquiry_id"] == inq.id and second["created"] is False
    assert db.query(Inquiry).filter_by(tenant_id=w.t.id, guest_id=mirrored.id).count() == 1
    assert client.post(f"{API}/leads", json={"phone": "12345"}, headers=_h(w.res)).status_code == 422
    assert client.post(f"{API}/leads", json={"phone": "9845012399"}, headers=_h(w.foh)).status_code == 403


def test_add_lead_for_a_brand_new_number(client, db, w):
    out = client.post(f"{API}/leads", json={"phone": "9845099999", "name": "Asha", "source": "other"}, headers=_h(w.res)).json()
    db.expire_all()
    g = db.query(Guest).filter_by(id=out["guest_id"]).one()
    assert g.name == "Asha" and g.lead_identified_at is not None and out["source"] is None


def test_context_prefills_from_the_lead_and_applies_the_lead_rules(client, db, w):
    g = person(db, w.t.id, "Anita Rao")
    inq = lead(db, w, guest=g)
    inq.check_in, inq.check_out, inq.adults, inq.children = START, (TODAY + timedelta(days=14)).isoformat(), 5, 1
    inq.route_mentioned = "Coorg"
    db.commit()
    out = client.get(f"{API}/context", params={"inquiry_id": inq.id}, headers=_h(w.res)).json()
    assert out["lead"]["inquiry_id"] == inq.id and out["trip"] == {"start_date": START, "days": 2, "guests": 6, "route": "Coorg",
                                                                    "package_key": "coorg-48"}
    assert out["filled"] == ["route", "dates", "guests"]
    by_phone = client.get(f"{API}/context", params={"phone": g.phone}, headers=_h(w.res)).json()
    assert by_phone["lead"]["inquiry_id"] == inq.id
    unknown = client.get(f"{API}/context", params={"phone": "9845077777"}, headers=_h(w.res)).json()
    assert unknown["lead"] is None and unknown["add"]["phone"] == "+919845077777"
    other = _user(db, _tenant(db).id, UserRole.OWNER)
    assert client.get(f"{API}/context", params={"inquiry_id": inq.id}, headers=_h(other)).status_code == 404


# ─── settings and the paid quote ──────────────────────────────────────────────────────────────────────────

def test_settings_owner_or_manager_only(client, db, w):
    new = {"gst_percent": "5", "prices_include_gst": False, "advance_percent": "30", "valid_days": 5,
           "approval_threshold_percent": "15", "max_discount_percent": "10", "greeting": "Hello"}
    assert client.put(f"{API}/settings", json=new, headers=_h(w.res)).status_code == 403
    res = client.put(f"{API}/settings", json=new, headers=_h(w.mgr))
    assert res.status_code == 200 and res.json()["gst_percent"] == "5" and res.json()["valid_days"] == 5
    out = client.post(f"{API}/price", json=body(gst_percent=None, prices_include_gst=None), headers=_h(w.res)).json()
    assert (out["gst"], out["total"], out["advance"]) == ("3500", "73500.00", "22050") and out["message_text"].startswith("Hello there")


def test_paid_calculator_quote_books_and_invoices_with_the_quote_tax(client, db, w, rzp):
    from app.models.property import Stay
    from app.models.stay_finance import StayPaymentLink
    from app.models.tenant import Tenant
    from app.services import invoice_service, quote_payment_service
    from tests.test_invoices import PROFILE
    connect_razorpay(db, w.t.id)
    approve_quote_template(db, w.t.id)
    inq = lead(db, w)
    out = save(client, w.res, inq, action="send", payment_link=True, gst_percent="5", prices_include_gst=False).json()
    assert out["message"]["status"] == "queued" and out["total"] == "73500.00"
    link = db.query(StayPaymentLink).filter_by(tenant_id=w.t.id).one()
    tenant = db.query(Tenant).filter_by(id=w.t.id).one()
    with patch("app.workers.tasks.invoice_tasks.after_payment.delay"):
        assert quote_payment_service.on_quote_link_paid(db, tenant, link, "pay_C1", float(link.amount), "upi") == "booked"
    stay = db.query(Stay).filter_by(tenant_id=w.t.id).one()
    assert float(stay.total_amount) == 73500 and "GST 5% added on top" in stay.internal_notes
    tenant.brand_config = {**(tenant.brand_config or {}), "invoice_profile": dict(PROFILE, gst_rate=18)}
    db.commit()
    inv = invoice_service.issue_invoice(db, tenant, stay)
    assert float(inv.gst_rate) == 5 and float(inv.total) == 73500
    assert float(inv.cgst + inv.sgst + inv.igst) == pytest.approx(float(Decimal("73500") - Decimal("70000")))


def test_the_lead_card_and_timeline_show_the_latest_quote(client, db, w):
    inq = lead(db, w)
    out = save(client, w.owner, inq, action="copy").json()
    detail = client.get(f"/api/v1/leads/{inq.id}", headers=_h(w.owner))
    assert detail.status_code == 200, detail.text
    d = detail.json()
    assert d["latest_quote"]["quote_id"] == out["quote_id"] and d["latest_quote"]["how"] == "copied"
    assert d["latest_quote"]["amount"] == 70000 and d["latest_quote"]["valid_until_text"]
    quote_lines = [e for e in d["timeline"] if e["channel"] == "quote"]
    assert quote_lines and quote_lines[0]["content_preview"].startswith("Quote ₹70,000 · Coorg 48-hour Retreat · copied · valid till")
    assert d["quote_history"][0]["shared_via"] == "copied" and d["quote_history"][0]["label"] == "Coorg 48-hour Retreat"
    listed = client.get("/api/v1/leads", headers=_h(w.owner)).json()
    card = next(c for c in listed["leads"] if c["inquiry_id"] == inq.id)
    assert card["latest_quote"]["quote_id"] == out["quote_id"]
