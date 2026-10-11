"""Meta webhook verify tokens: hidden by default, owner-only reveal, per workspace and per channel."""
import os
import uuid

from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.core.config import settings  # noqa: E402
from app.core.encryption import encrypt_credentials  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.models.integration import Integration  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402

LEGACY = "legacy-shared-token-value"


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _connect(db, tenant_id, kind):
    db.add(Integration(tenant_id=tenant_id, kind=kind, status="active", config={},
                       credentials_kms_blob=encrypt_credentials({"access_token": "x"})))
    db.commit()


def _verify(client, channel, token, mode="subscribe"):
    return client.get(f"/api/v1/webhooks/{channel}", params={"hub.mode": mode, "hub.verify_token": token, "hub.challenge": "CH4LLENGE"})


def _second_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    owner = User(id=str(uuid.uuid4()), tenant_id=t.id, name="O2", email=f"o2-{uuid.uuid4().hex[:6]}@t.com",
                 hashed_password="x", role=UserRole.OWNER, is_active=True)
    db.add(owner)
    db.commit()
    return t, {"Authorization": "Bearer " + create_access_token({"sub": owner.id, "tenant_id": t.id, "role": "owner"})}


def test_webhook_info_never_contains_the_token(client, db, tenant_and_user, monkeypatch):
    monkeypatch.setattr(settings, "META_WHATSAPP_WEBHOOK_VERIFY_TOKEN", LEGACY)
    tid, h = tenant_and_user["tenant"].id, _h(tenant_and_user)
    _connect(db, tid, "whatsapp_meta")
    _connect(db, tid, "instagram")

    for kind in ("whatsapp_meta", "instagram"):
        info = client.get(f"/api/v1/integrations/{kind}/webhook-info", headers=h).json()
        assert LEGACY not in str(info) and "verify_token" not in info
        assert info["verify_token_set"] is False and info["can_reveal"] is True and info["legacy_token_active"] is True

    token = client.post("/api/v1/integrations/whatsapp_meta/verify-token/reveal", headers=h).json()["verify_token"]
    info = client.get("/api/v1/integrations/whatsapp_meta/webhook-info", headers=h).json()
    assert token not in str(info) and info["verify_token_set"] is True and info["verify_token_hint"] == f"...{token[-4:]}"


def test_reveal_is_owner_only_logged_stable_and_needs_a_connected_channel(client, db, tenant_and_user):
    tid, slug, h = tenant_and_user["tenant"].id, tenant_and_user["tenant"].slug, _h(tenant_and_user)
    assert client.post("/api/v1/integrations/instagram/verify-token/reveal", headers=h).status_code == 404     # not connected yet
    assert client.post("/api/v1/integrations/nonsense/verify-token/reveal", headers=h).status_code == 404
    _connect(db, tid, "instagram")

    first = client.post("/api/v1/integrations/instagram/verify-token/reveal", headers=h).json()
    again = client.post("/api/v1/integrations/instagram/verify-token/reveal", headers=h).json()
    assert first["verify_token"].startswith(f"{slug}.") and first["verify_token"] == again["verify_token"] and first["rotated"] is False

    mgr = User(id=str(uuid.uuid4()), tenant_id=tid, name="M", email=f"m-{uuid.uuid4().hex[:6]}@t.com",
               hashed_password="x", role=UserRole.MANAGER, is_active=True)
    db.add(mgr)
    db.commit()
    mh = {"Authorization": "Bearer " + create_access_token({"sub": mgr.id, "tenant_id": tid, "role": "manager"})}
    assert client.post("/api/v1/integrations/instagram/verify-token/reveal", headers=mh).status_code == 403
    assert client.post("/api/v1/integrations/instagram/verify-token/rotate", headers=mh).status_code == 403
    info = client.get("/api/v1/integrations/instagram/webhook-info", headers=mh).json()          # a manager still sees the URL
    assert info["webhook_url"].endswith("/webhooks/instagram") and info["can_reveal"] is False and first["verify_token"] not in str(info)

    from app.models.audit_event import AuditEvent
    events = db.query(AuditEvent).filter_by(tenant_id=tid, action="integration.verify_token_revealed").all()
    assert len(events) == 2 and "verify_token" not in str(events[0].payload)                     # the secret is never logged


def test_each_channel_and_workspace_has_its_own_token(client, db, tenant_and_user, monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_LEGACY_WEBHOOK_VERIFY_TOKEN", False)
    tid, h = tenant_and_user["tenant"].id, _h(tenant_and_user)
    other, oh = _second_tenant(db)
    for t in (tid, other.id):
        _connect(db, t, "whatsapp_meta")
        _connect(db, t, "instagram")
    wa = client.post("/api/v1/integrations/whatsapp_meta/verify-token/reveal", headers=h).json()["verify_token"]
    ig = client.post("/api/v1/integrations/instagram/verify-token/reveal", headers=h).json()["verify_token"]
    other_wa = client.post("/api/v1/integrations/whatsapp_meta/verify-token/reveal", headers=oh).json()["verify_token"]
    assert len({wa, ig, other_wa}) == 3

    assert _verify(client, "whatsapp", wa).text == "CH4LLENGE"
    assert _verify(client, "instagram", ig).text == "CH4LLENGE"
    assert _verify(client, "instagram", wa).status_code == 403                  # a WhatsApp token does not verify Instagram
    assert _verify(client, "whatsapp", ig).status_code == 403
    assert _verify(client, "whatsapp", other_wa).text == "CH4LLENGE"            # the other workspace's own token verifies its own channel
    forged = f"{other.slug}.{wa.split('.', 1)[1]}"
    assert _verify(client, "whatsapp", forged).status_code == 403              # another workspace's slug with this one's secret
    assert _verify(client, "whatsapp", "").status_code == 403
    assert _verify(client, "whatsapp", wa, mode="unsubscribe").status_code == 403


def test_rotate_kills_the_old_token_and_is_audited(client, db, tenant_and_user, monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_LEGACY_WEBHOOK_VERIFY_TOKEN", False)
    tid, h = tenant_and_user["tenant"].id, _h(tenant_and_user)
    _connect(db, tid, "whatsapp_meta")
    old = client.post("/api/v1/integrations/whatsapp_meta/verify-token/reveal", headers=h).json()["verify_token"]
    new = client.post("/api/v1/integrations/whatsapp_meta/verify-token/rotate", headers=h).json()
    assert new["rotated"] is True and new["verify_token"] != old
    assert _verify(client, "whatsapp", old).status_code == 403
    assert _verify(client, "whatsapp", new["verify_token"]).text == "CH4LLENGE"

    from app.models.audit_event import AuditEvent
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="integration.verify_token_rotated").count() == 1


def test_legacy_shared_token_still_verifies_until_switched_off(client, db, tenant_and_user, monkeypatch):
    monkeypatch.setattr(settings, "META_WHATSAPP_WEBHOOK_VERIFY_TOKEN", LEGACY)
    monkeypatch.setattr(settings, "ALLOW_LEGACY_WEBHOOK_VERIFY_TOKEN", True)
    assert _verify(client, "whatsapp", LEGACY).text == "CH4LLENGE"
    assert _verify(client, "instagram", LEGACY).text == "CH4LLENGE"
    assert _verify(client, "whatsapp", LEGACY + "x").status_code == 403
    monkeypatch.setattr(settings, "ALLOW_LEGACY_WEBHOOK_VERIFY_TOKEN", False)
    assert _verify(client, "whatsapp", LEGACY).status_code == 403
    monkeypatch.setattr(settings, "ALLOW_LEGACY_WEBHOOK_VERIFY_TOKEN", True)
    monkeypatch.setattr(settings, "META_WHATSAPP_WEBHOOK_VERIFY_TOKEN", "")                  # unset legacy token never matches anything
    assert _verify(client, "whatsapp", "").status_code == 403


def test_token_survives_credential_updates_elsewhere(client, db, tenant_and_user):
    """The token lives in the encrypted credential blob: saving other credentials must not wipe it."""
    from app.services import webhook_verify_service as wvs
    tid, h = tenant_and_user["tenant"].id, _h(tenant_and_user)
    _connect(db, tid, "instagram")
    token = client.post("/api/v1/integrations/instagram/verify-token/reveal", headers=h).json()["verify_token"]
    assert wvs.current_token(db, tid, "instagram") == token
    intg = wvs.find_integration(db, tid, "instagram")
    creds = wvs._blob(intg)
    assert creds["access_token"] == "x" and creds[wvs.KEY] == token                            # other credentials untouched alongside it
