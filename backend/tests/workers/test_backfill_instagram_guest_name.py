"""
backfill_instagram_guest_name() username fallback.

Found live: Meta's Instagram Send API user-profile endpoint no longer
reliably returns "name" for most business integrations (platform
restriction), only "profile_pic" and "id" -- confirmed against Ratha's
real access token. Requesting "username" explicitly still works, so the
task should fall back to "@handle" instead of leaving the guest stuck on
the numeric "IG User ######" placeholder forever.
"""
import os
import uuid
from unittest.mock import patch

from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.models.tenant import Tenant
from app.models.integration import Integration
from app.models.guest import Guest
from app.core.encryption import encrypt_credentials
from app.workers.tasks import process_instagram_dm as mod
from app.workers.tasks.process_instagram_dm import backfill_instagram_guest_name


class _NoCloseSessionWrapper:
    """The task calls SessionLocal() to open its own DB session -- a real
    second connection that can't see the test fixture's uncommitted
    transaction. Wrap the fixture's own session instead, with .close() as
    a no-op so the test's later assertions still see the same rows."""
    def __init__(self, real_db):
        self._real_db = real_db

    def __getattr__(self, name):
        return getattr(self._real_db, name)

    def close(self):
        pass


def _make_tenant(db):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(t)
    db.flush()
    return t


def _make_ig_integration(db, tenant_id):
    integration = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant_id, kind="instagram", status="active",
        credentials_kms_blob=encrypt_credentials({"access_token": "tok"}),
        config={"instagram_business_account_id": "ig-biz-001"},
    )
    db.add(integration)
    db.flush()
    return integration


def _make_placeholder_guest(db, tenant_id, sender_id="929817850128977"):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name=f"IG User {sender_id[-6:]}", phone="")
    db.add(g)
    db.flush()
    return g


def test_falls_back_to_username_when_name_missing(db):
    """Reproduces Meta's actual response shape for this endpoint today:
    no "name" key at all, but "username" present."""
    tenant = _make_tenant(db)
    _make_ig_integration(db, tenant.id)
    guest = _make_placeholder_guest(db, tenant.id)
    db.commit()

    with patch.object(mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch(
        "app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_user_profile",
        return_value={"username": "life_through_my_lensss", "profile_pic": "https://...", "id": "929817850128977"},
    ):
        result = backfill_instagram_guest_name.run(tenant_id=tenant.id, guest_id=guest.id, sender_id="929817850128977")

    assert result["status"] == "ok", result
    db.refresh(guest)
    assert guest.name == "@life_through_my_lensss"


def test_prefers_real_name_over_username_when_both_present(db):
    tenant = _make_tenant(db)
    _make_ig_integration(db, tenant.id)
    guest = _make_placeholder_guest(db, tenant.id)
    db.commit()

    with patch.object(mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch(
        "app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_user_profile",
        return_value={"name": "Real Name", "username": "handle"},
    ):
        backfill_instagram_guest_name.run(tenant_id=tenant.id, guest_id=guest.id, sender_id="929817850128977")

    db.refresh(guest)
    assert guest.name == "Real Name"


def test_no_name_or_username_leaves_placeholder(db):
    tenant = _make_tenant(db)
    _make_ig_integration(db, tenant.id)
    guest = _make_placeholder_guest(db, tenant.id)
    db.commit()

    with patch.object(mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch(
        "app.adapters.instagram.meta_graph.InstagramGraphAdapter.get_user_profile",
        return_value={"profile_pic": "https://...", "id": "929817850128977"},
    ):
        result = backfill_instagram_guest_name.run(tenant_id=tenant.id, guest_id=guest.id, sender_id="929817850128977")

    assert result["status"] == "no_name_available"
    db.refresh(guest)
    assert guest.name.startswith("IG User ")
