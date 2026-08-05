"""Tests for PATCH /integrations/vobiz/did-number -- lets an already-
connected Vobiz integration add/update just the DID number without a full
disconnect/reconnect (which would rotate webhook_secret and break the live
inbound Answer URL already pasted into the tenant's Vobiz Console)."""
import uuid

from app.models.integration import Integration
from app.core.encryption import encrypt_credentials, decrypt_credentials


def _connect_vobiz(db, tenant_id, **overrides):
    creds = {
        "webhook_secret": "wh-secret", "api_key": "MA123", "api_secret": "tenant-token",
        "forward_number": "+919000000000",
    }
    creds.update(overrides)
    integration = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant_id, kind="vobiz", status="active",
        credentials_kms_blob=encrypt_credentials(creds),
    )
    db.add(integration)
    db.commit()
    return integration


def test_requires_did_number_in_body(client, tenant_and_user, db):
    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id)

    res = client.patch(
        "/api/v1/integrations/vobiz/did-number",
        json={},
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 400


def test_404s_when_vobiz_not_connected(client, tenant_and_user):
    res = client.patch(
        "/api/v1/integrations/vobiz/did-number",
        json={"did_number": "+912271264296"},
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 404


def test_updates_did_number_without_touching_other_creds(client, tenant_and_user, db):
    tenant = tenant_and_user["tenant"]
    integration = _connect_vobiz(db, tenant.id)

    res = client.patch(
        "/api/v1/integrations/vobiz/did-number",
        json={"did_number": "+912271264296"},
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 200

    db.refresh(integration)
    creds = decrypt_credentials(integration.credentials_kms_blob)
    assert creds["did_number"] == "+912271264296"
    # Untouched.
    assert creds["api_key"] == "MA123"
    assert creds["api_secret"] == "tenant-token"
    assert creds["forward_number"] == "+919000000000"
    assert creds["webhook_secret"] == "wh-secret"


def test_overwrites_existing_did_number(client, tenant_and_user, db):
    tenant = tenant_and_user["tenant"]
    integration = _connect_vobiz(db, tenant.id, did_number="+91OLDNUMBER")

    res = client.patch(
        "/api/v1/integrations/vobiz/did-number",
        json={"did_number": "+912271264296"},
        headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"},
    )
    assert res.status_code == 200
    db.refresh(integration)
    assert decrypt_credentials(integration.credentials_kms_blob)["did_number"] == "+912271264296"


def test_requires_owner_or_manager_role(client, tenant_and_user, db):
    import hashlib
    from app.models.user import User, UserRole, RefreshToken
    from app.core.security import create_access_token, get_password_hash

    tenant = tenant_and_user["tenant"]
    _connect_vobiz(db, tenant.id)

    agent = User(
        id=str(uuid.uuid4()), tenant_id=tenant.id, name="Agent", email=f"agent-{uuid.uuid4().hex[:6]}@test.com",
        hashed_password=get_password_hash("testpassword123"), role=UserRole.FOH, is_active=True,
    )
    db.add(agent)
    db.commit()
    token = create_access_token({"sub": agent.id, "tenant_id": tenant.id, "role": agent.role.value})

    res = client.patch(
        "/api/v1/integrations/vobiz/did-number",
        json={"did_number": "+912271264296"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403
