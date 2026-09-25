"""Hourly alert for "the Instagram account owner switched message access off".

Real incident (Ratha, 24-Sep-2026): about 15 hours of Instagram DMs never
reached the inbox while the access token was perfectly valid. The account's
own "Allow access to messages" switch was off, so Meta refused every Direct
Messaging call with 403 "The account owner has disabled access to Instagram
Direct Messaging" and sent no message events. The existing daily token check
only reads the account node, so it could not see it.

The probe asks for one page of conversations and alerts on that exact refusal
-- and on nothing else (a dead token, missing Advanced Access, an outage).
"""
import os
import uuid
from unittest.mock import MagicMock, patch

import httpx
from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.core.encryption import encrypt_credentials
from app.models.integration import Integration
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.workers.celery_app import celery_app
from app.workers.tasks import check_meta_credentials as mod

TASK = mod.check_instagram_dm_access_tenant
EMAIL_FN = "app.services.email_service.send_instagram_dm_access_alert_email"

_DISABLED = {"error": {
    "message": "The account owner has disabled access to Instagram Direct Messaging.",
    "type": "IGApiException", "code": 200, "fbtrace_id": "AmRys",
}}


class _Resp:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = str(self._body)

    def json(self):
        return self._body


class _MemoryCache:
    """Redis is optional in tests and does nothing when absent, so the dedupe
    logic is tested against a plain dict with the same get/set contract."""
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ttl=300):
        self.store[key] = value


def _tenant(db, name="Ratha"):
    t = Tenant(id=str(uuid.uuid4()), name=name, slug=f"ig-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _owner(db, tenant_id, email):
    u = User(id=str(uuid.uuid4()), tenant_id=tenant_id, email=email, name="Owner",
             role=UserRole.OWNER, is_active=True, is_deleted=False)
    db.add(u)
    db.commit()
    return u


def _instagram(db, tenant_id, status="active"):
    row = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant_id, kind="instagram", status=status,
        config={"instagram_business_account_id": "ig-1"},
        credentials_kms_blob=encrypt_credentials({"access_token": "IGAAtoken"}),
    )
    db.add(row)
    db.commit()
    return row


def _run(db, tenant_id, cache, *, get=None, email=None):
    """Run the per-tenant task with Meta, the email and the cache stubbed."""
    with patch.object(mod, "SessionLocal", return_value=db), \
         patch.object(mod, "get_cached", side_effect=cache.get), \
         patch.object(mod, "set_cached", side_effect=cache.set), \
         patch("httpx.get", **(get or {"return_value": _Resp(200, {"data": []})})) as http, \
         patch(EMAIL_FN) as mail:
        result = TASK.run(tenant_id=tenant_id)
    return result, http, mail


# ── what counts as "switched off" ───────────────────────────────────────────

def test_message_access_off_alerts_the_owner_with_the_right_email(db):
    t = _tenant(db)
    _owner(db, t.id, "owner@ratha.test")
    _instagram(db, t.id)

    result, http, mail = _run(db, t.id, _MemoryCache(), get={"return_value": _Resp(403, _DISABLED)})

    assert result == {"tenant_id": t.id, "status": "disabled", "alerts_sent": 1}
    _, kwargs = mail.call_args
    assert kwargs == {"to_email": "owner@ratha.test", "tenant_name": "Ratha"}
    url = http.call_args.args[0]
    assert url.startswith("https://graph.instagram.com") and url.endswith("/me/conversations")


def test_message_access_on_sends_nothing(db):
    t = _tenant(db)
    _owner(db, t.id, "owner@ratha.test")
    _instagram(db, t.id)

    result, _, mail = _run(db, t.id, _MemoryCache())

    assert result["status"] == "open" and result["alerts_sent"] == 0
    assert not mail.called


def test_only_the_message_access_refusal_alerts(db):
    """A dead token, a missing permission, an outage and a timeout all say
    nothing about the switch -- the daily token check owns the first, and a
    false "you turned it off" email would be worse than silence."""
    t = _tenant(db)
    _owner(db, t.id, "owner@ratha.test")
    _instagram(db, t.id)

    inconclusive = [
        {"return_value": _Resp(403, {"error": {"message": "Invalid OAuth access token.", "code": 190}})},
        {"return_value": _Resp(403, {"error": {"message": "Requires instagram_business_manage_messages "
                                                          "Advanced Access", "code": 10}})},
        # code 200 is also Meta's number for ordinary permission errors
        {"return_value": _Resp(403, {"error": {"message": "(#200) Permissions error", "code": 200}})},
        {"return_value": _Resp(500, {"error": {"message": "temporarily unavailable"}})},
        {"return_value": _Resp(429, {"error": {"message": "rate limited", "code": 4}})},
        {"side_effect": httpx.ConnectTimeout("slow")},
        {"return_value": _Resp(403, "not json")},
    ]
    for get in inconclusive:
        result, _, mail = _run(db, t.id, _MemoryCache(), get=get)
        assert result["status"] == "skipped", get
        assert not mail.called, get


# ── who gets probed ─────────────────────────────────────────────────────────

def test_a_connection_marked_error_is_still_probed(db):
    """"error" is a failed check, not the owner disconnecting -- and it is
    exactly the state a message-access problem tends to leave behind."""
    t = _tenant(db)
    _owner(db, t.id, "owner@ratha.test")
    _instagram(db, t.id, status="error")

    result, _, mail = _run(db, t.id, _MemoryCache(), get={"return_value": _Resp(403, _DISABLED)})

    assert result["alerts_sent"] == 1 and mail.called


def test_disconnected_or_missing_instagram_makes_no_call(db):
    t = _tenant(db)
    _owner(db, t.id, "owner@ratha.test")
    _instagram(db, t.id, status="disconnected")
    result, http, mail = _run(db, t.id, _MemoryCache(), get={"return_value": _Resp(403, _DISABLED)})
    assert result["status"] == "skipped" and not http.called and not mail.called

    t2 = _tenant(db, "No Instagram")
    _owner(db, t2.id, "owner@other.test")
    result, http, mail = _run(db, t2.id, _MemoryCache(), get={"return_value": _Resp(403, _DISABLED)})
    assert result["status"] == "skipped" and not http.called and not mail.called


def test_another_workspaces_owner_is_never_emailed(db):
    ratha, other = _tenant(db, "Ratha"), _tenant(db, "Other Villa")
    _owner(db, ratha.id, "owner@ratha.test")
    _owner(db, other.id, "owner@other.test")
    _instagram(db, ratha.id)
    _instagram(db, other.id)

    _, _, mail = _run(db, ratha.id, _MemoryCache(), get={"return_value": _Resp(403, _DISABLED)})

    assert [c.kwargs["to_email"] for c in mail.call_args_list] == ["owner@ratha.test"]


# ── not a mailbox flood ─────────────────────────────────────────────────────

def test_it_alerts_once_while_it_stays_off_then_again_after_a_relapse(db):
    t = _tenant(db)
    _owner(db, t.id, "owner@ratha.test")
    _instagram(db, t.id)
    cache = _MemoryCache()
    off = {"return_value": _Resp(403, _DISABLED)}
    on = {"return_value": _Resp(200, {"data": []})}

    _, _, first = _run(db, t.id, cache, get=off)
    second_result, _, second = _run(db, t.id, cache, get=off)      # next hour, still off
    assert first.call_count == 1
    assert second_result["alerts_sent"] == 0 and not second.called

    _run(db, t.id, cache, get=on)                                    # fixed
    _, _, third = _run(db, t.id, cache, get=off)                    # switched off again
    assert third.call_count == 1


def test_a_failed_send_is_retried_next_hour_not_next_day(db):
    t = _tenant(db)
    _owner(db, t.id, "owner@ratha.test")
    _instagram(db, t.id)
    cache = _MemoryCache()
    off = {"return_value": _Resp(403, _DISABLED)}

    with patch.object(mod, "SessionLocal", return_value=db), \
         patch.object(mod, "get_cached", side_effect=cache.get), \
         patch.object(mod, "set_cached", side_effect=cache.set), \
         patch("httpx.get", **off), \
         patch(EMAIL_FN, return_value=False) as mail:          # provider said no
        result = TASK.run(tenant_id=t.id)
    assert result["alerts_sent"] == 0

    _, _, retry = _run(db, t.id, cache, get=off)
    assert retry.call_count == 1                                # tried again, not silenced


# ── wiring: the schedule really reaches the task ────────────────────────────

def test_the_hourly_schedule_and_queue_point_at_registered_tasks():
    """A schedule string that doesn't match a registered task name fires and
    is silently ignored -- seven existing entries were found doing exactly that."""
    celery_app.loader.import_default_modules()
    entry = celery_app.conf.beat_schedule["instagram-dm-access-hourly"]
    assert entry["task"] in celery_app.tasks
    routes = celery_app.conf.task_routes
    for name in ("meta_credentials.check_instagram_dm_access",
                 "meta_credentials.check_instagram_dm_access_tenant"):
        assert name in celery_app.tasks
        assert routes[name] == {"queue": "whatsapp"}


def test_the_fan_out_queues_one_probe_per_active_tenant(db):
    active = _tenant(db, "A")
    inactive = _tenant(db, "B")
    inactive.is_active = False
    db.commit()

    with patch.object(mod, "SessionLocal", return_value=MagicMock(
            query=lambda *_a, **_k: MagicMock(filter=lambda *_x: MagicMock(all=lambda: [active])),
            close=lambda: None)), \
         patch.object(mod.check_instagram_dm_access_tenant, "apply_async") as queued:
        result = mod.check_instagram_dm_access_all.run()

    assert result == {"tenants_queued": 1}
    queued.assert_called_once_with(kwargs={"tenant_id": active.id}, queue="whatsapp")


def test_the_email_tells_the_right_story():
    import asyncio
    from app.services import email_service

    sent = {}

    async def fake_send(to, subject, html):
        sent.update(to=to, subject=subject, html=html)
        return True

    with patch.object(email_service, "_send", fake_send):
        asyncio.run(email_service.send_instagram_dm_access_alert_email(
            to_email="owner@ratha.test", tenant_name="Ratha <b>Caravans</b>"))

    assert "aren't reaching HAIP" in sent["subject"]
    assert "Allow access to messages" in sent["html"]
    assert "token expired" not in sent["html"].lower()          # not the wrong diagnosis
    assert "<b>Caravans</b>" not in sent["html"]                 # tenant name is escaped
    assert "&lt;b&gt;Caravans&lt;/b&gt;" in sent["html"]
