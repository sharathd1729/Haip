"""WhatsApp connection health, and the two ways the App Secret used to go missing.

Real incident (Ratha, Sep 2026): sends were accepted by Meta but stayed at
"sent" forever, and a guest's reply never appeared. Meta's webhook is refused
without the tenant's App Secret; the connect form called it "recommended" and a
reconnect with the box blank overwrote the saved one with an empty string.
"""
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.core.encryption import decrypt_credentials, encrypt_credentials
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState
from app.models.guest import Guest
from app.models.integration import Integration
from app.services import wa_health_service as svc

URL = "https://api.example.com/api/v1/webhooks/whatsapp"


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _connect(db, tid, app_secret="secret", config=None, token="tok"):
    row = Integration(
        id=str(uuid.uuid4()), tenant_id=tid, kind="whatsapp_meta", status="active",
        config={"phone_number_id": "pn1", "waba_id": "waba1", **(config or {})},
        credentials_kms_blob=encrypt_credentials({"access_token": token, "app_secret": app_secret, "phone_number_id": "pn1", "waba_id": "waba1"}),
    )
    db.add(row)
    db.commit()
    return row


class _Resp:
    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


def _meta(phone=None, subscribed=None, boom=None):
    """A stand-in for Meta's Graph API, answering by URL."""
    phone = phone if phone is not None else {"display_phone_number": "+91 98456 63366", "verified_name": "Ratha by Jade"}
    subscribed = subscribed if subscribed is not None else {"data": [{"whatsapp_business_api_data": {"id": "app1"}}]}

    def get(url, params=None, timeout=None):
        if boom:
            raise boom
        return _Resp(subscribed if url.endswith("/subscribed_apps") else phone)
    return get


def _check(db, tid, **meta):
    with patch("app.services.wa_health_service.httpx.get", side_effect=_meta(**meta)):
        return svc.check(db, tid, URL)


def _by_key(result):
    return {c["key"]: c for c in result["checks"]}


# ─── the check ───────────────────────────────────────────────────────────────

def test_not_connected(db, tenant_and_user):
    r = _check(db, _tid(tenant_and_user))
    assert r["status"] == "fail" and r["checks"][0]["key"] == "connection" and "Settings" in r["checks"][0]["fix"]


def test_a_healthy_connection(db, tenant_and_user):
    _connect(db, _tid(tenant_and_user))
    r = _check(db, _tid(tenant_and_user))
    c = _by_key(r)
    assert r["status"] == "ok"
    assert c["token"]["status"] == "ok" and "Ratha by Jade" in c["token"]["detail"]
    assert c["app_secret"]["status"] == "ok" and c["subscription"]["status"] == "ok"
    assert c["activity"]["status"] == "ok" and "Nothing received yet" in c["activity"]["title"]


def test_a_missing_app_secret_is_named_as_the_cause(db, tenant_and_user):
    _connect(db, _tid(tenant_and_user), app_secret="")
    r = _check(db, _tid(tenant_and_user))
    c = _by_key(r)["app_secret"]
    assert r["status"] == "fail" and c["status"] == "fail"
    assert "stay at “sent”" in c["detail"] and "Settings → Basic" in c["fix"]


def test_an_expired_token(db, tenant_and_user):
    _connect(db, _tid(tenant_and_user))
    r = _check(db, _tid(tenant_and_user), phone={"error": {"code": 190, "message": "Error validating access token"}})
    t = _by_key(r)["token"]
    assert t["status"] == "fail" and "Error validating access token" in t["detail"] and "190" in t["detail"]


def test_a_network_failure_is_reported_not_raised(db, tenant_and_user):
    _connect(db, _tid(tenant_and_user))
    r = _check(db, _tid(tenant_and_user), boom=ConnectionError("down"))
    assert "Couldn't reach Meta" in _by_key(r)["token"]["detail"]


def test_an_app_that_is_not_subscribed(db, tenant_and_user):
    _connect(db, _tid(tenant_and_user))
    r = _check(db, _tid(tenant_and_user), subscribed={"data": []})
    s = _by_key(r)["subscription"]
    assert r["status"] == "fail" and "isn't subscribed" in s["title"] and "messages" in s["fix"]


def test_a_phone_level_webhook_override_elsewhere_is_caught(db, tenant_and_user):
    _connect(db, _tid(tenant_and_user))
    phone = {"display_phone_number": "+91 1", "verified_name": "X", "webhook_configuration": {"application": "https://old.example.com/hook"}}
    r = _check(db, _tid(tenant_and_user), phone=phone)
    assert _by_key(r)["override"]["status"] == "fail" and "old.example.com" in _by_key(r)["override"]["detail"]
    same = {**phone, "webhook_configuration": {"application": URL + "/"}}
    assert "override" not in _by_key(_check(db, _tid(tenant_and_user), phone=same))


def test_a_refused_webhook_is_reported_with_its_reason(db, tenant_and_user):
    row = _connect(db, _tid(tenant_and_user), config={
        "webhook_ok_at": "2026-09-01T10:00:00+00:00", "webhook_rejected_at": "2026-09-20T10:00:00+00:00", "webhook_rejected_reason": "bad_signature"})
    r = _check(db, _tid(tenant_and_user))
    a = _by_key(r)["activity"]
    assert r["status"] == "fail" and "refusing" in a["title"] and "doesn't match" in a["detail"]


def test_a_webhook_that_works_again_clears_the_refusal(db, tenant_and_user):
    _connect(db, _tid(tenant_and_user), config={
        "webhook_rejected_at": "2026-09-01T10:00:00+00:00", "webhook_rejected_reason": "no_app_secret", "webhook_ok_at": "2026-09-24T10:00:00+00:00"})
    a = _by_key(_check(db, _tid(tenant_and_user)))["activity"]
    assert a["status"] == "ok" and "Last update received" in a["detail"]


def _sent_message(db, tid, minutes_ago=90):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="G", phone="+919876500001")
    db.add(g); db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(c); db.flush()
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=c.id, direction="outbound", channel=ChannelType.WHATSAPP, body="x",
                   delivery_state=MessageDeliveryState.SENT, channel_message_id=f"wamid.{uuid.uuid4().hex[:6]}",
                   created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)))
    db.commit()


def test_messages_stuck_at_sent_with_no_word_from_meta_raise_a_warning(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _connect(db, tid)
    _sent_message(db, tid); _sent_message(db, tid)
    r = _check(db, tid)
    a = _by_key(r)["activity"]
    assert a["status"] == "warn" and a["title"].startswith("2 messages sent but never confirmed")
    assert r["facts"]["stuck_sent"] == 2


def test_a_message_sent_moments_ago_is_not_stuck(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _connect(db, tid)
    _sent_message(db, tid, minutes_ago=5)
    assert _check(db, tid)["facts"]["stuck_sent"] == 0


def test_health_is_scoped_to_the_workspace(db, tenant_and_user):
    _connect(db, _tid(tenant_and_user))
    other = str(uuid.uuid4())
    assert _check(db, other)["checks"][0]["key"] == "connection"


# ─── remembering what Meta's webhook did ─────────────────────────────────────

def test_a_refusal_is_recorded_and_success_is_throttled(db, tenant_and_user):
    row = _connect(db, _tid(tenant_and_user))
    svc.note_webhook(db, row, ok=False, reason="no_app_secret")
    assert row.config["webhook_rejected_reason"] == "no_app_secret" and row.config["webhook_rejected_at"]
    svc.note_webhook(db, row, ok=True)
    first = row.config["webhook_ok_at"]
    row.config = {**row.config, "webhook_ok_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}
    stamp = row.config["webhook_ok_at"]
    svc.note_webhook(db, row, ok=True)                       # inside 5 minutes: no write
    assert row.config["webhook_ok_at"] == stamp and first


# ─── connecting ──────────────────────────────────────────────────────────────

def _connect_call(client, tu, **fields):
    body = {"phone_number_id": "pn1", "waba_id": "waba1", "access_token": "new-token", **fields}
    with patch("app.api.v1.endpoints.integrations.httpx.get", side_effect=_meta()):
        return client.post("/api/v1/integrations/whatsapp_meta/connect-key", json=body,
                           headers={"Authorization": f"Bearer {tu['access_token']}"})


def _saved(db, tid):
    row = db.query(Integration).filter_by(tenant_id=tid, kind="whatsapp_meta").one()
    db.refresh(row)
    return decrypt_credentials(row.credentials_kms_blob)


def test_reconnecting_with_the_box_blank_keeps_the_saved_secret(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _connect(db, tid, app_secret="the-real-secret", token="old-token")
    r = _connect_call(client, tenant_and_user)                       # new token, App Secret left blank
    assert r.status_code == 200
    creds = _saved(db, tid)
    assert creds["app_secret"] == "the-real-secret" and creds["access_token"] == "new-token"
    assert not (r.json().get("warning") or "").startswith("No App Secret")


def test_a_new_secret_replaces_the_old_one(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _connect(db, tid, app_secret="old")
    _connect_call(client, tenant_and_user, app_secret="brand-new")
    assert _saved(db, tid)["app_secret"] == "brand-new"


def test_connecting_without_any_secret_warns_in_words(client, db, tenant_and_user):
    r = _connect_call(client, tenant_and_user)
    assert r.status_code == 200
    assert "No App Secret is saved" in r.json()["warning"] and "delivery updates" in r.json()["warning"]


# ─── the webhook records what it does ────────────────────────────────────────

class _Keep:
    def __init__(self, s):
        self._s = s

    def __getattr__(self, n):
        return getattr(self._s, n)

    def close(self):
        pass


def _hook(client, db, body, sig):
    with patch("app.api.v1.endpoints.webhooks_whatsapp.SessionLocal", return_value=_Keep(db)), \
         patch("app.workers.tasks.whatsapp.process_whatsapp_message.delay"):
        return client.post("/api/v1/webhooks/whatsapp", content=body, headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig})


def _payload():
    return json.dumps({"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "pn1"}, "messages": [], "statuses": []}}]}]}).encode()


def _sig(body, secret):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_the_webhook_remembers_a_missing_secret(client, db, tenant_and_user):
    row = _connect(db, _tid(tenant_and_user), app_secret="")
    body = _payload()
    assert _hook(client, db, body, _sig(body, "x")).status_code == 401
    db.refresh(row)
    assert row.config["webhook_rejected_reason"] == "no_app_secret"


def test_the_webhook_remembers_a_wrong_secret_then_a_good_call(client, db, tenant_and_user):
    row = _connect(db, _tid(tenant_and_user), app_secret="right")
    body = _payload()
    assert _hook(client, db, body, _sig(body, "wrong")).status_code == 401
    db.refresh(row)
    assert row.config["webhook_rejected_reason"] == "bad_signature"
    assert _hook(client, db, body, _sig(body, "right")).status_code == 200
    db.refresh(row)
    assert row.config["webhook_ok_at"]
    a = _by_key(_check(db, _tid(tenant_and_user)))["activity"]
    assert a["status"] == "ok"                                       # the later success supersedes the earlier refusal


# ─── endpoint ────────────────────────────────────────────────────────────────

def test_the_health_endpoint(client, db, tenant_and_user):
    _connect(db, _tid(tenant_and_user))
    with patch("app.services.wa_health_service.httpx.get", side_effect=_meta()):
        r = client.get("/api/v1/messaging/whatsapp/health", headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"})
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["webhook_url"].endswith("/api/v1/webhooks/whatsapp")


def test_the_health_endpoint_is_role_checked(client, db, tenant_and_user):
    from app.core.security import create_access_token
    from app.models.user import User, UserRole
    u = User(id=str(uuid.uuid4()), tenant_id=_tid(tenant_and_user), name="A", email=f"a-{uuid.uuid4().hex[:6]}@t.com",
             hashed_password="x", role=UserRole.CONCIERGE, is_active=True)
    db.add(u); db.commit()
    token = create_access_token({"sub": u.id, "tenant_id": u.tenant_id, "role": "concierge"})
    assert client.get("/api/v1/messaging/whatsapp/health", headers={"Authorization": f"Bearer {token}"}).status_code == 403
