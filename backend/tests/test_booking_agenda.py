"""Bookings agenda (layout B): segments + counts, multi-value filters, the month summary, the vehicle strip,
the WhatsApp thread for a booking and the window-aware pay link. SQLite run; PostgreSQL not run for this file."""
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.core.encryption import encrypt_credentials  # noqa: E402
from app.core.security import create_access_token, get_password_hash  # noqa: E402
from app.models.base import gen_uuid  # noqa: E402
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.integration import Integration  # noqa: E402
from app.models.property import BlockedDate, Property, Stay  # noqa: E402
from app.models.stay_finance import StayDeposit, StayInstalment, StayPayment  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.services import booking_agenda_service as agenda  # noqa: E402
from tests.conftest import seed_capabilities  # noqa: E402

pytestmark = pytest.mark.usefixtures("capabilities_seeded")

T = datetime.now(ZoneInfo("Asia/Kolkata")).date()   # "today" for a workspace with the default timezone (IST)


def _d(n):
    return T + timedelta(days=n)


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _role(db, tid, role):
    u = User(id=str(uuid.uuid4()), tenant_id=tid, name=role, email=f"{role}-{uuid.uuid4().hex[:6]}@t.com",
             hashed_password=get_password_hash("pw"), role=UserRole(role), is_active=True)
    db.add(u)
    db.commit()
    return {"Authorization": "Bearer " + create_access_token({"sub": u.id, "tenant_id": tid, "role": role})}


def _prop(db, tid, name):
    p = Property(id=gen_uuid(), tenant_id=tid, name=name, slug=f"p-{uuid.uuid4().hex[:6]}", type="caravan", is_active=True)
    db.add(p)
    db.flush()
    return p


def _guest(db, tid, name="Asha Rao"):
    g = Guest(id=gen_uuid(), tenant_id=tid, name=name, phone=f"+9199{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    db.flush()
    return g


def _stay(db, tid, prop, guest, a, b, status="confirmed", total=20000, paid=0):
    s = Stay(id=gen_uuid(), tenant_id=tid, guest_id=guest.id, property_id=prop.id, check_in=_d(a), check_out=_d(b),
             status=status, total_amount=total, channel_source="direct")
    db.add(s)
    db.flush()
    if paid:
        db.add(StayPayment(tenant_id=tid, stay_id=s.id, kind="payment", amount=paid, method="upi", paid_on=T))
    return s


def _other_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    seed_capabilities(db, t.id)
    return t


@pytest.fixture()
def world(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    r1, r2 = _prop(db, tid, "Ratha 1"), _prop(db, tid, "Ratha 2")
    g = _guest(db, tid)
    w = {
        "tid": tid, "r1": r1, "r2": r2, "g": g,
        "today_in": _stay(db, tid, r1, g, 0, 2, paid=5000),            # checks in today: upcoming
        "later": _stay(db, tid, r2, g, 5, 7),                          # upcoming, unpaid
        "staying": _stay(db, tid, r2, g, -1, 1, paid=20000),           # started yesterday, confirmed: staying
        "checked_in": _stay(db, tid, r1, g, -3, -1, status="checked_in"),  # not checked out yet: staying
        "ended": _stay(db, tid, r1, g, -9, -7),                        # confirmed, ended: past
        "checked_out": _stay(db, tid, r2, g, -5, -4, status="checked_out", paid=20000),
        "cancelled": _stay(db, tid, r1, g, 3, 4, status="cancelled"),
    }
    o = _other_tenant(db)
    op, og = _prop(db, o.id, "Ratha 1"), _guest(db, o.id, "Zed")
    w["foreign"] = _stay(db, o.id, op, og, 1, 2)
    db.commit()
    return w


def _ids(client, tu, **params):
    r = client.get("/api/v1/bookings", params={"per_page": 100, **params}, headers=_h(tu))
    assert r.status_code == 200, r.text
    return r.json()


def test_segments_partition_bookings_and_counts_follow_the_filters(client, world, tenant_and_user):
    w = world
    body = _ids(client, tenant_and_user, segment="upcoming", counts="true", sort="check_in_asc")
    assert [b["id"] for b in body["data"]] == [w["today_in"].id, w["later"].id]
    assert body["meta"]["segment_counts"] == {"upcoming": 2, "staying": 2, "past": 2, "cancelled": 1}
    assert body["meta"]["today"] == T.isoformat() and tuple(body["meta"]["segment_counts"]) == agenda.SEGMENTS
    assert {b["id"] for b in _ids(client, tenant_and_user, segment="staying")["data"]} == {w["staying"].id, w["checked_in"].id}
    assert {b["id"] for b in _ids(client, tenant_and_user, segment="past")["data"]} == {w["ended"].id, w["checked_out"].id}
    assert {b["id"] for b in _ids(client, tenant_and_user, segment="cancelled")["data"]} == {w["cancelled"].id}
    # Another workspace's booking never shows or counts.
    assert w["foreign"].id not in {b["id"] for b in _ids(client, tenant_and_user)["data"]}
    # Counts honour the other filters: only Ratha 2.
    c = _ids(client, tenant_and_user, segment="upcoming", counts="true", property_id=w["r2"].id)["meta"]["segment_counts"]
    assert c == {"upcoming": 1, "staying": 1, "past": 1, "cancelled": 0}
    assert client.get("/api/v1/bookings", params={"segment": "soon"}, headers=_h(tenant_and_user)).status_code == 422


def test_filters_take_several_values_and_check_in_dates(client, world, tenant_and_user):
    w = world
    got = {b["id"] for b in _ids(client, tenant_and_user, status="cancelled,checked_out")["data"]}
    assert got == {w["cancelled"].id, w["checked_out"].id}
    got = {b["id"] for b in _ids(client, tenant_and_user, property_id=f"{w['r1'].id},{w['r2'].id}", check_in_from=_d(0).isoformat(),
                                 check_in_to=_d(5).isoformat())["data"]}
    assert got == {w["today_in"].id, w["later"].id, w["cancelled"].id}
    assert client.get("/api/v1/bookings", params={"payment_status": "paid,nope"}, headers=_h(tenant_and_user)).status_code == 422
    assert client.get("/api/v1/bookings", params={"check_in_from": "19-10"}, headers=_h(tenant_and_user)).status_code == 422


def test_overdue_means_trip_started_or_an_instalment_past_due(client, db, world, tenant_and_user):
    w = world
    # "later" is unpaid with an instalment due yesterday: overdue. "today_in" is part paid, nothing past due: not overdue.
    db.add(StayInstalment(tenant_id=w["tid"], stay_id=w["later"].id, label="Advance", amount=10000, due_date=_d(-1)))
    db.add(StayInstalment(tenant_id=w["tid"], stay_id=w["today_in"].id, label="Advance", amount=5000, due_date=_d(-2)))
    db.commit()
    got = {b["id"] for b in _ids(client, tenant_and_user, payment_status="overdue")["data"]}
    # checked_in (started, unpaid) and ended (unpaid) owe money after the trip started; cancelled never owes.
    assert got == {w["later"].id, w["checked_in"].id, w["ended"].id}
    row = next(b for b in _ids(client, tenant_and_user, segment="upcoming")["data"] if b["id"] == w["later"].id)
    assert row["payment_overdue"] is True and row["raw_status"] == "confirmed"


def test_list_rows_carry_deposit_and_trip(client, db, world, tenant_and_user):
    w = world
    db.add(StayDeposit(tenant_id=w["tid"], stay_id=w["staying"].id, amount=10000, status="held"))
    db.commit()
    row = next(b for b in _ids(client, tenant_and_user, segment="staying")["data"] if b["id"] == w["staying"].id)
    assert row["deposit"] == {"amount": 10000.0, "status": "held"}
    assert row["total"] == 20000 and row["total_paid"] == 20000      # the deposit is not in the total or the paid figure


def test_month_summary_money_needs_revenue_read_and_skips_cancelled_and_deposits(client, db, world, tenant_and_user):
    w = world
    db.add(StayDeposit(tenant_id=w["tid"], stay_id=w["today_in"].id, amount=10000, status="held"))
    db.commit()
    month = T.strftime("%Y-%m")
    r = client.get("/api/v1/bookings/summary", params={"month": month}, headers=_h(tenant_and_user))
    assert r.status_code == 200, r.text
    body = r.json()
    in_month = [s for k, s in w.items() if k not in ("tid", "r1", "r2", "g", "foreign", "cancelled")
                and isinstance(s, Stay) and s.check_in.strftime("%Y-%m") == month]
    assert body["bookings"] == len(in_month)
    totals = {"today_in": (20000, 5000), "later": (20000, 0), "staying": (20000, 20000), "checked_in": (20000, 0),
              "ended": (20000, 0), "checked_out": (20000, 20000)}
    keys = [k for k in totals if w[k] in in_month]
    assert body["booked_value"] == sum(totals[k][0] for k in keys)
    assert body["collected"] == sum(totals[k][1] for k in keys)          # the 10,000 deposit is not collected revenue
    assert body["still_due"] == body["booked_value"] - body["collected"]
    assert [v["name"] for v in body["by_vehicle"]] == sorted(v["name"] for v in body["by_vehicle"])

    concierge = _role(db, w["tid"], "concierge")                         # bookings.read, no revenue.read
    c = client.get("/api/v1/bookings/summary", params={"month": month}, headers=concierge).json()
    assert c["bookings"] == body["bookings"]
    assert c["booked_value"] == {"restricted": True} and c["collected"] == {"restricted": True}
    assert c["still_due"] == {"restricted": True} and c["overdue"] == {"restricted": True}
    assert client.get("/api/v1/bookings/summary", headers=_role(db, w["tid"], "marketing")).status_code == 403
    assert client.get("/api/v1/bookings/summary", params={"month": "2026-13"}, headers=_h(tenant_and_user)).status_code == 422


def test_occupancy_strip_lists_each_vehicle_with_due_marker(client, db, world, tenant_and_user):
    w = world
    db.add(BlockedDate(tenant_id=w["tid"], property_id=w["r1"].id, blocked_from=_d(8).isoformat(), blocked_to=_d(10).isoformat(),
                       reason="maintenance", is_active=True))
    placeholder = _prop(db, w["tid"], "Unassigned")
    db.commit()
    r = client.get("/api/v1/bookings/occupancy", params={"days": 14}, headers=_h(tenant_and_user))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["today"] == T.isoformat() and body["from"] == T.isoformat() and body["to"] == _d(14).isoformat()
    names = [v["name"] for v in body["vehicles"]]
    assert names == ["Ratha 1", "Ratha 2"]                          # the empty placeholder is not a row
    r1 = body["vehicles"][0]
    by_id = {b["booking_id"]: b for b in r1["bookings"]}
    assert set(by_id) == {w["today_in"].id}                         # checked_in ended yesterday; cancelled is not a hold
    assert by_id[w["today_in"].id]["due"] is True
    assert r1["holds"] == [{"from": _d(8).isoformat(), "to": _d(10).isoformat(), "reason": "maintenance"}]
    r2 = {b["booking_id"]: b for b in body["vehicles"][1]["bookings"]}
    assert set(r2) == {w["later"].id, w["staying"].id} and r2[w["staying"].id]["due"] is False
    assert w["foreign"].id not in str(body)

    _stay(db, w["tid"], placeholder, w["g"], 2, 3)
    db.commit()
    names = [v["name"] for v in client.get("/api/v1/bookings/occupancy", headers=_h(tenant_and_user)).json()["vehicles"]]
    assert names == ["Ratha 1", "Ratha 2", "Unassigned"]
    assert client.get("/api/v1/bookings/occupancy", headers=_role(db, w["tid"], "marketing")).status_code == 403


def _inbound(db, tid, guest, hours_ago):
    conv = Conversation(id=gen_uuid(), tenant_id=tid, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True,
                        last_message_at=datetime.now(timezone.utc).isoformat())
    db.add(conv)
    db.flush()
    db.add(Message(id=gen_uuid(), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.INBOUND,
                   channel=ChannelType.WHATSAPP, body="hi", created_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago)))
    db.commit()
    return conv


def test_booking_detail_reports_the_whatsapp_window(client, db, world, tenant_and_user):
    w = world
    h = _h(tenant_and_user)
    assert client.get(f"/api/v1/bookings/{w['later'].id}", headers=h).json()["whatsapp"] == {
        "conversation_id": None, "last_inbound_at": None, "window_open": False}
    conv = _inbound(db, w["tid"], w["g"], hours_ago=2)
    wa = client.get(f"/api/v1/bookings/{w['later'].id}", headers=h).json()["whatsapp"]
    assert wa["conversation_id"] == conv.id and wa["window_open"] is True


def test_whatsapp_thread_opens_one_and_is_tenant_scoped(client, db, world, tenant_and_user):
    w = world
    h = _h(tenant_and_user)
    r = client.post(f"/api/v1/bookings/{w['later'].id}/whatsapp-thread", headers=h)
    assert r.status_code == 200, r.text
    first = r.json()["conversation_id"]
    assert first and r.json()["window_open"] is False
    assert client.post(f"/api/v1/bookings/{w['later'].id}/whatsapp-thread", headers=h).json()["conversation_id"] == first
    assert client.post(f"/api/v1/bookings/{w['foreign'].id}/whatsapp-thread", headers=h).status_code == 404
    assert client.post(f"/api/v1/bookings/{w['later'].id}/whatsapp-thread", headers=_role(db, w["tid"], "read_only")).status_code == 403


def _rzp(db, tid):
    db.add(Integration(tenant_id=tid, kind="razorpay", status="active", config={},
                       credentials_kms_blob=encrypt_credentials({"key_id": "rzp_test_abc12345", "key_secret": "s3cretvalue",
                                                                 "webhook_secret": "whsec"})))
    db.commit()


def _fake_link(key_id, key_secret, **kw):
    return {"id": f"plink_{uuid.uuid4().hex[:8]}", "short_url": "https://rzp.io/i/abc"}


def test_pay_link_goes_as_a_normal_message_inside_the_window(client, db, world, tenant_and_user):
    w = world
    _rzp(db, w["tid"])
    conv = _inbound(db, w["tid"], w["g"], hours_ago=1)
    task = MagicMock()
    with patch("app.api.v1.endpoints.booking_detail.rzp.create_payment_link", side_effect=_fake_link), \
            patch("app.workers.tasks.send_whatsapp.send_whatsapp", task):
        r = client.post(f"/api/v1/bookings/{w['later'].id}/payment-links", json={"send_whatsapp": True}, headers=_h(tenant_and_user))
    assert r.status_code == 201, r.text
    assert r.json()["whatsapp"] == {"status": "queued", "reason": None, "via": "text"}
    assert task.delay.call_count == 1
    msg = db.query(Message).filter_by(conversation_id=conv.id, direction=MessageDirection.OUTBOUND).one()
    assert "https://rzp.io/i/abc" in msg.body and "₹20,000" in msg.body


def test_pay_link_uses_the_template_when_the_window_is_closed(client, db, world, tenant_and_user):
    w = world
    _rzp(db, w["tid"])
    _inbound(db, w["tid"], w["g"], hours_ago=30)
    sent = MagicMock(return_value={"status": "skipped", "reason": "template not approved", "message_id": None})
    with patch("app.api.v1.endpoints.booking_detail.rzp.create_payment_link", side_effect=_fake_link), \
            patch("app.services.wa_booking_messages.send_balance_due", sent):
        r = client.post(f"/api/v1/bookings/{w['later'].id}/payment-links", json={"send_whatsapp": True}, headers=_h(tenant_and_user))
    assert r.status_code == 201, r.text
    assert r.json()["whatsapp"] == {"status": "skipped", "reason": "template not approved", "via": "template"}
    assert sent.call_count == 1
