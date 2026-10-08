"""Outbound webhooks: endpoint management, event capture, signing, delivery and retries."""
import hashlib
import hmac
import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.core.security import create_access_token  # noqa: E402
from app.models.base import gen_uuid  # noqa: E402
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState, MessageDirection  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.property import Property, Stay  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.models.webhook import WebhookDelivery, WebhookEndpoint  # noqa: E402
from app.services import webhook_service as ws  # noqa: E402

DELAY = "app.workers.tasks.webhook_delivery.deliver_webhook.delay"


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _d(n):
    return date.today() + timedelta(days=n)


def _endpoint(db, tid, events=("booking.created", "booking.updated", "booking.cancelled", "payment.received"), url="https://hooks.example.com/haip"):
    ep, secret = ws.create_endpoint(db, tid, url, list(events), "test", None)
    db.commit()
    return ep, secret


def _property(db, tid):
    p = Property(id=gen_uuid(), tenant_id=tid, name="Caravan 1", slug=f"c-{uuid.uuid4().hex[:6]}", type="villa", is_active=True)
    db.add(p)
    db.commit()
    return p


def _booking(client, tu, prop, phone="+919876543210"):
    r = client.post("/api/v1/bookings", headers=_h(tu), json={
        "property_id": prop.id, "guest_phone": phone, "guest_name": "Asha", "check_in": _d(5).isoformat(),
        "check_out": _d(7).isoformat(), "adults": 2, "total_amount": 10000})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _deliveries(db, tid, event_type=None):
    q = db.query(WebhookDelivery).filter_by(tenant_id=tid)
    if event_type:
        q = q.filter_by(event_type=event_type)
    return q.order_by(WebhookDelivery.created_at).all()


# ─── Management API ───────────────────────────────────────────────────────────

def test_endpoint_lifecycle_and_secret_shown_once(client, db, tenant_and_user):
    h = _h(tenant_and_user)
    with patch("app.api.v1.endpoints.webhook_endpoints.assert_public_url"):
        r = client.post("/api/v1/webhook-endpoints", headers=h, json={"url": "https://ops.example.com/hook", "events": ["booking.created"]})
        assert r.status_code == 201, r.text
        created = r.json()
        assert created["secret"].startswith("whsec_")

        listed = client.get("/api/v1/webhook-endpoints", headers=h).json()
        assert [e["id"] for e in listed["endpoints"]] == [created["id"]]
        assert "secret" not in listed["endpoints"][0] and "booking.updated" in [e["event"] for e in listed["events"]]

        rotated = client.patch(f"/api/v1/webhook-endpoints/{created['id']}", headers=h, json={"rotate_secret": True}).json()
        assert rotated["secret"].startswith("whsec_") and rotated["secret"] != created["secret"]
        assert client.patch(f"/api/v1/webhook-endpoints/{created['id']}", headers=h, json={"events": ["booking.updated"]}).json()["events"] == ["booking.updated"]
        assert client.delete(f"/api/v1/webhook-endpoints/{created['id']}", headers=h).status_code == 204
    assert client.get("/api/v1/webhook-endpoints", headers=h).json()["endpoints"] == []


def test_endpoint_validation_and_roles(client, db, tenant_and_user):
    h = _h(tenant_and_user)
    assert client.post("/api/v1/webhook-endpoints", headers=h, json={"url": "http://insecure.example.com/h", "events": ["booking.created"]}).status_code == 422
    with patch("app.api.v1.endpoints.webhook_endpoints.assert_public_url"):
        assert client.post("/api/v1/webhook-endpoints", headers=h, json={"url": "https://a.example.com/h", "events": ["nope"]}).status_code == 422
        assert client.post("/api/v1/webhook-endpoints", headers=h, json={"url": "https://a.example.com/h", "events": []}).status_code == 422

    mgr = User(id=str(uuid.uuid4()), tenant_id=tenant_and_user["tenant"].id, name="M", email=f"m-{uuid.uuid4().hex[:6]}@t.com",
               hashed_password="x", role=UserRole.MANAGER, is_active=True)
    db.add(mgr)
    db.commit()
    mh = {"Authorization": "Bearer " + create_access_token({"sub": mgr.id, "tenant_id": mgr.tenant_id, "role": "manager"})}
    assert client.post("/api/v1/webhook-endpoints", headers=mh, json={"url": "https://a.example.com/h", "events": ["booking.created"]}).status_code == 403
    assert client.get("/api/v1/webhook-endpoints", headers=mh).status_code == 200


def test_other_tenants_endpoint_is_404(client, db, tenant_and_user):
    t2 = Tenant(id=str(uuid.uuid4()), name="O", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t2)
    db.flush()
    other, _ = _endpoint(db, t2.id)
    h = _h(tenant_and_user)
    for method, path in [("patch", ""), ("delete", ""), ("post", "/test"), ("get", "/deliveries")]:
        assert getattr(client, method)(f"/api/v1/webhook-endpoints/{other.id}{path}", headers=h, **({"json": {}} if method == "patch" else {})).status_code == 404


# ─── Signing ──────────────────────────────────────────────────────────────────

def test_signature_matches_documented_scheme():
    body = b'{"id":"evt_1"}'
    expected = "v1=" + hmac.new(b"whsec_x", b"1760000000." + body, hashlib.sha256).hexdigest()
    assert ws.sign("whsec_x", 1760000000, body) == expected


# ─── Event capture ────────────────────────────────────────────────────────────

def test_booking_lifecycle_emits_events_once_each(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    prop = _property(db, tid)
    ep, _ = _endpoint(db, tid)
    with patch(DELAY) as delay:
        stay_id = _booking(client, tenant_and_user, prop)
        created = _deliveries(db, tid, "booking.created")
        assert len(created) == 1 and created[0].endpoint_id == ep.id and created[0].status == "pending"
        data = created[0].payload["data"]
        assert created[0].payload["type"] == "booking.created" and data["id"] == stay_id and data["guest"]["phone"] == "+919876543210"
        assert delay.call_count == 1 and delay.call_args.kwargs["delivery_id"] == created[0].id

        r = client.post(f"/api/v1/bookings/{stay_id}/payments", headers=_h(tenant_and_user), json={"amount": 4000, "method": "upi"})
        assert r.status_code == 201
        assert len(_deliveries(db, tid, "payment.received")) == 1
        pay = _deliveries(db, tid, "payment.received")[0].payload["data"]
        assert pay["booking_id"] == stay_id and pay["amount"] == 4000
        updated = _deliveries(db, tid, "booking.updated")
        assert len(updated) == 1 and updated[0].payload["data"]["financials"]["paid"] == 4000

        r = client.patch(f"/api/v1/bookings/{stay_id}", headers=_h(tenant_and_user), json={"status": "cancelled"})
        assert r.status_code == 200, r.text
    assert len(_deliveries(db, tid, "booking.cancelled")) == 1
    assert len(_deliveries(db, tid, "booking.updated")) == 1          # cancelling is not also reported as an update


def test_no_event_when_unsubscribed_inactive_or_other_tenant(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    prop = _property(db, tid)
    _endpoint(db, tid, events=("payment.received",))
    off, _ = _endpoint(db, tid, events=("booking.created",), url="https://off.example.com/h")
    off.is_active = False
    t2 = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t2)
    db.flush()
    foreign, _ = _endpoint(db, t2.id, events=("booking.created",))
    db.commit()
    with patch(DELAY):
        _booking(client, tenant_and_user, prop)
    assert _deliveries(db, tid) == []
    assert _deliveries(db, t2.id) == []


def test_rolled_back_change_emits_nothing(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    prop = _property(db, tid)
    _endpoint(db, tid)
    guest = Guest(id=gen_uuid(), tenant_id=tid, name="G", phone="+919811100001")
    db.add(guest)
    db.flush()
    db.add(Stay(id=gen_uuid(), tenant_id=tid, guest_id=guest.id, property_id=prop.id, check_in=_d(1), check_out=_d(2), status="confirmed"))
    db.flush()
    db.rollback()
    with patch(DELAY) as delay:
        db.commit()
    assert _deliveries(db, tid) == [] and delay.call_count == 0


def test_message_events(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    _endpoint(db, tid, events=("message.received", "message.status"))
    guest = Guest(id=gen_uuid(), tenant_id=tid, name="Asha", phone="+919811100002")
    db.add(guest)
    db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv)
    db.commit()

    with patch(DELAY):
        db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.INBOUND,
                       channel=ChannelType.WHATSAPP, body="Is the gate open?"))
        db.commit()
        rec = _deliveries(db, tid, "message.received")
        assert len(rec) == 1 and rec[0].payload["data"]["text"] == "Is the gate open?" and rec[0].payload["data"]["guest"]["phone"] == "+919811100002"

        out = Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.OUTBOUND,
                      channel=ChannelType.WHATSAPP, body="Yes", delivery_state=MessageDeliveryState.QUEUED,
                      channel_metadata={"local_message_id": "ops-9"})
        db.add(out)
        db.commit()
        assert _deliveries(db, tid, "message.status") == []              # creating it is not a status change
        out.delivery_state = MessageDeliveryState.DELIVERED
        db.commit()
        st = _deliveries(db, tid, "message.status")
        assert len(st) == 1 and st[0].payload["data"]["status"] == "delivered" and st[0].payload["data"]["local_message_id"] == "ops-9"

        out.sender_name = "someone"                                       # unrelated edit: no event
        db.commit()
    assert len(_deliveries(db, tid, "message.status")) == 1


# ─── Delivery ────────────────────────────────────────────────────────────────

def _pending(db, tid, ep, event_type="booking.updated"):
    env = ws.envelope(event_type, {"id": "b1"})
    d = WebhookDelivery(tenant_id=tid, endpoint_id=ep.id, event_id=env["id"], event_type=event_type, payload=env,
                        status="pending", attempts=0, next_attempt_at=datetime.now(timezone.utc))
    db.add(d)
    db.commit()
    return d


def _client(status, seen=None):
    def handler(request: httpx.Request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_successful_delivery_is_signed_and_verifiable(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    ep, secret = _endpoint(db, tid)
    d = _pending(db, tid, ep)
    seen = []
    with patch("app.services.webhook_service.assert_public_url"):
        assert ws.deliver(db, d.id, tid, client=_client(204, seen)) == "success"

    req = seen[0]
    ts, sig = req.headers["x-haip-timestamp"], req.headers["x-haip-signature"]
    expected = "v1=" + hmac.new(secret.encode(), ts.encode() + b"." + req.content, hashlib.sha256).hexdigest()
    assert hmac.compare_digest(sig, expected)
    assert req.headers["x-haip-event"] == "booking.updated" and req.headers["x-haip-delivery"] == d.id
    assert json.loads(req.content)["id"] == d.event_id
    db.refresh(d)
    db.refresh(ep)
    assert d.status == "success" and d.attempts == 1 and d.delivered_at and ep.consecutive_failures == 0 and ep.last_success_at


def test_failures_back_off_then_give_up(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    ep, _ = _endpoint(db, tid)
    d = _pending(db, tid, ep)
    with patch("app.services.webhook_service.assert_public_url"):
        assert ws.deliver(db, d.id, tid, client=_client(500)) == "pending"
        db.refresh(d)
        assert d.attempts == 1 and d.response_status == 500 and "HTTP 500" in d.last_error
        wait = d.next_attempt_at.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc) if d.next_attempt_at.tzinfo is None else d.next_attempt_at - datetime.now(timezone.utc)
        assert timedelta(seconds=15) < wait <= ws.BACKOFF[0]

        for _ in range(ws.MAX_ATTEMPTS - 1):
            ws.deliver(db, d.id, tid, client=_client(503))
            db.refresh(d)
    assert d.status == "failed" and d.attempts == ws.MAX_ATTEMPTS and d.next_attempt_at is None
    db.refresh(ep)
    assert ep.consecutive_failures == ws.MAX_ATTEMPTS


def test_unreachable_server_and_blocked_url_are_recorded_not_raised(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    ep, _ = _endpoint(db, tid)
    d = _pending(db, tid, ep)

    def boom(request):
        raise httpx.ConnectError("refused")
    with patch("app.services.webhook_service.assert_public_url"):
        assert ws.deliver(db, d.id, tid, client=httpx.Client(transport=httpx.MockTransport(boom))) == "pending"
    db.refresh(d)
    assert "ConnectError" in d.last_error

    from app.core.url_safety import UnsafeURLError
    d2 = _pending(db, tid, ep)
    with patch("app.services.webhook_service.assert_public_url", side_effect=UnsafeURLError("private address")):
        assert ws.deliver(db, d2.id, tid, client=_client(200)) == "failed"       # never retried: it would be blocked again
    db.refresh(d2)
    assert "Blocked" in d2.last_error


def test_endpoint_switches_off_after_many_failures_and_can_be_re_enabled(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    ep, _ = _endpoint(db, tid)
    ep.consecutive_failures = ws.DISABLE_AFTER_FAILURES - 1
    d = _pending(db, tid, ep)
    with patch("app.services.webhook_service.assert_public_url"):
        ws.deliver(db, d.id, tid, client=_client(500))
    db.refresh(ep)
    assert ep.is_active is False and "failed deliveries" in ep.disabled_reason

    r = client.patch(f"/api/v1/webhook-endpoints/{ep.id}", headers=_h(tenant_and_user), json={"is_active": True})
    assert r.json()["is_active"] is True and r.json()["consecutive_failures"] == 0 and r.json()["disabled_reason"] is None


def test_test_ping_reports_what_the_server_answered(client, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    ep, _ = _endpoint(db, tid, events=("booking.created",))              # ping works even when not subscribed
    fake = MagicMock()
    fake.post.return_value = httpx.Response(200)
    with patch("app.services.webhook_service.assert_public_url"), patch("app.services.webhook_service.httpx.Client", return_value=fake):
        r = client.post(f"/api/v1/webhook-endpoints/{ep.id}/test", headers=_h(tenant_and_user))
    assert r.status_code == 200 and r.json()["status"] == "success" and r.json()["event_type"] == "ping"
    sent = fake.post.call_args.kwargs
    assert json.loads(sent["content"])["type"] == "ping"

    deliveries = client.get(f"/api/v1/webhook-endpoints/{ep.id}/deliveries", headers=_h(tenant_and_user)).json()["deliveries"]
    assert [x["event_type"] for x in deliveries] == ["ping"]


def test_retry_due_task_picks_up_only_due_pending(db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    ep, _ = _endpoint(db, tid)
    due = _pending(db, tid, ep)
    later = _pending(db, tid, ep)
    later.next_attempt_at = datetime.now(timezone.utc) + timedelta(hours=1)
    done = _pending(db, tid, ep)
    done.status = "success"
    db.commit()

    from app.workers.tasks import webhook_delivery as task
    with patch.object(task, "SessionLocal", return_value=db), patch.object(db, "close"), \
            patch.object(task.deliver_webhook, "apply_async") as send:
        task.retry_due()
    ids = [c.kwargs["kwargs"]["delivery_id"] for c in send.call_args_list]
    assert ids == [due.id]


def test_task_routing_and_schedule_registered():
    from app.workers.celery_app import celery_app
    for name in ("webhooks.deliver", "webhooks.retry_due", "webhooks.purge_old"):
        assert celery_app.conf.task_routes[name]["queue"] == "call_ingest"
    assert celery_app.conf.beat_schedule["webhooks-retry-due-1min"]["task"] == "webhooks.retry_due"


def test_docs_describe_webhooks_and_signature():
    from app.public_api.app import app as public_app
    spec = public_app.openapi()
    assert {"booking-event", "payment-received", "message-received", "message-status"} <= set(spec["webhooks"])
    assert "X-HAIP-Signature" in spec["info"]["description"] and "hmac.compare_digest" in spec["info"]["description"]
