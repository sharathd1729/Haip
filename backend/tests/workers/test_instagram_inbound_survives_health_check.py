"""Instagram DMs must not stop arriving because a health check said "error".

Real incident (Ratha, Sep 2026, "Instagram stopped again"): the Integrations
page's "Test connection" button checked Instagram against graph.facebook.com.
The integration is connected through Instagram Login, whose tokens only work
on graph.instagram.com -- there Meta answers HTTP 400 "Cannot parse access
token". The endpoint only expected a 401, so it fell into its catch-all, wrote
status="error" onto a perfectly healthy integration, and every inbound DM was
then dropped as "no matching active integration". Meta got a 200, never
retried, and the messages never reached the inbox.

Two things are pinned here: the check no longer breaks a healthy integration,
and inbound no longer depends on the token being healthy at all (it never uses
the token -- only sending does).
"""
import os
import uuid
from unittest.mock import patch

import httpx
from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.core.encryption import encrypt_credentials
from app.models.conversation import Message
from app.models.integration import Integration
from app.models.tenant import Tenant
from app.workers.tasks import process_instagram_comment as comment_mod
from app.workers.tasks import process_instagram_dm as dm_mod

IG_ID = "ig-biz-001"


class _NoCloseSessionWrapper:
    def __init__(self, real_db):
        self._real_db = real_db

    def __getattr__(self, name):
        return getattr(self._real_db, name)

    def close(self):
        pass


class _Resp:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.text = str(self._body)

    def json(self):
        return self._body


_INVALID_TOKEN = {"error": {"message": "Invalid OAuth access token - Cannot parse access token",
                            "type": "OAuthException", "code": 190}}
_EXPIRED_TOKEN = {"error": {"message": "Error validating access token: Session has expired",
                            "type": "OAuthException", "code": 190, "error_subcode": 463}}


def _integration(db, tenant_id, status="active"):
    row = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant_id, kind="instagram", status=status,
        credentials_kms_blob=encrypt_credentials({"access_token": "IGAAtoken", "instagram_business_account_id": IG_ID}),
        config={"instagram_business_account_id": IG_ID},
    )
    db.add(row)
    db.commit()
    return row


def _instagram_only(seen):
    """Meta's real behaviour: an Instagram Login token works on
    graph.instagram.com and is rejected on graph.facebook.com."""
    def fake_get(url, **kwargs):
        seen.append(url)
        if url.startswith("https://graph.instagram.com"):
            return _Resp(200, {"id": IG_ID, "username": "ratha_caravans"})
        return _Resp(400, _INVALID_TOKEN)
    return fake_get


def _test_button(client, tenant_and_user):
    headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    return client.post("/api/v1/integrations/instagram/test", headers=headers)


def _dm(mid=None):
    return {
        "ig_account_id": IG_ID, "sender_id": "ig-sender-1", "text": "hi, saw your reel",
        "message_id": mid or f"mid-{uuid.uuid4().hex[:8]}", "attachments": [], "referral": None,
    }


def _run_dm(db, payload):
    with patch.object(dm_mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch("app.adapters.instagram.meta_graph.InstagramGraphAdapter") as adapter, \
         patch("app.workers.tasks.concierge_draft.concierge_draft") as concierge, \
         patch.object(dm_mod, "backfill_instagram_guest_name") as backfill:
        adapter.return_value.send_text.return_value = {"message_id": "x"}
        concierge.apply_async.return_value = None
        backfill.apply_async.return_value = None
        return dm_mod.process_instagram_dm.run(payload)


# ── the test button ──────────────────────────────────────────────────────────

def test_test_button_checks_instagram_on_the_instagram_host(client, db, tenant_and_user):
    row = _integration(db, tenant_and_user["tenant"].id)
    seen: list[str] = []
    with patch("app.api.v1.endpoints.integrations.httpx.get", side_effect=_instagram_only(seen)):
        res = _test_button(client, tenant_and_user)

    assert res.status_code == 200, res.text
    assert res.json()["status"] == "active", res.json()
    assert seen and all(u.startswith("https://graph.instagram.com") for u in seen), seen
    db.refresh(row)
    assert row.status == "active"


def test_test_button_repairs_an_integration_it_wrongly_switched_off(client, db, tenant_and_user):
    row = _integration(db, tenant_and_user["tenant"].id, status="error")
    with patch("app.api.v1.endpoints.integrations.httpx.get", side_effect=_instagram_only([])):
        res = _test_button(client, tenant_and_user)

    assert res.json()["status"] == "active"
    db.refresh(row)
    assert row.status == "active"


def test_a_slow_or_failing_meta_does_not_switch_instagram_off(client, db, tenant_and_user):
    row = _integration(db, tenant_and_user["tenant"].id)
    for failure in (
        {"side_effect": httpx.ConnectTimeout("slow")},
        {"return_value": _Resp(503, {"error": {"message": "temporarily unavailable"}})},
        {"return_value": _Resp(429, {"error": {"message": "rate limited", "code": 4}})},
    ):
        with patch("app.api.v1.endpoints.integrations.httpx.get", **failure):
            res = _test_button(client, tenant_and_user)
        body = res.json()
        assert body["status"] == "unverified", body                    # told to the user...
        assert "nothing was changed" in body["message"].lower()
        db.refresh(row)
        assert row.status == "active", failure                          # ...and nothing written


def test_a_genuinely_dead_token_is_still_reported(client, db, tenant_and_user):
    row = _integration(db, tenant_and_user["tenant"].id)
    dead = _Resp(400, _EXPIRED_TOKEN)
    with patch("app.api.v1.endpoints.integrations.httpx.get", return_value=dead):
        res = _test_button(client, tenant_and_user)

    assert res.json()["status"] == "error"
    assert "reconnect" in res.json()["message"].lower()
    db.refresh(row)
    assert row.status == "error"


# ── inbound does not depend on the token ────────────────────────────────────

def test_dms_still_arrive_while_the_token_is_marked_bad(db):
    tenant = Tenant(id=str(uuid.uuid4()), name="Ratha", slug=f"r-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant)
    db.flush()
    _integration(db, tenant.id, status="error")

    mid = f"mid-{uuid.uuid4().hex[:8]}"
    result = _run_dm(db, _dm(mid))

    assert result.get("status") != "skipped", result
    assert db.query(Message).filter_by(channel_message_id=mid).count() == 1


def test_comments_still_arrive_while_the_token_is_marked_bad(db):
    tenant = Tenant(id=str(uuid.uuid4()), name="Ratha", slug=f"r-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant)
    db.flush()
    _integration(db, tenant.id, status="error")

    with patch.object(comment_mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch("app.workers.tasks.process_instagram_dm.backfill_instagram_guest_name") as backfill:
        backfill.apply_async.return_value = None
        result = comment_mod.process_instagram_comment.run({
            "ig_account_id": IG_ID, "sender_id": "ig-commenter-1", "comment_id": "c1",
            "text": "how much per night?", "media_id": "m1", "media_ad_id": "", "media_ad_title": "",
            "sender_username": "curious_traveler",
        })

    assert result.get("reason") != "no integration", result


def test_a_disconnected_integration_still_drops_dms(db):
    """Disconnect means the owner turned it off -- that one must stay off."""
    tenant = Tenant(id=str(uuid.uuid4()), name="Ratha", slug=f"r-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant)
    db.flush()
    _integration(db, tenant.id, status="disconnected")

    mid = f"mid-{uuid.uuid4().hex[:8]}"
    result = _run_dm(db, _dm(mid))

    assert result == {"status": "skipped", "reason": "no integration"}
    assert db.query(Message).filter_by(channel_message_id=mid).count() == 0


def test_another_workspaces_integration_is_never_matched(db):
    """The account id decides the tenant -- a different IG account's DM must
    not land in this workspace even though its integration is also 'error'."""
    tenant = Tenant(id=str(uuid.uuid4()), name="Ratha", slug=f"r-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant)
    db.flush()
    _integration(db, tenant.id, status="error")

    payload = _dm()
    payload["ig_account_id"] = "some-other-account"
    result = _run_dm(db, payload)

    assert result == {"status": "skipped", "reason": "no integration"}
