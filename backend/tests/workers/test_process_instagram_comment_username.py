"""
process_instagram_comment.py: use the commenter's free username from the
webhook payload as the initial guest name, instead of unconditionally
creating a numeric "IG User ######" placeholder and queuing a backfill
API call that's consent-gated for DMs (confirmed live: essentially every
DM sender profile lookup 500s with IGApiException 230). Comments carry
"from.username" directly on the webhook -- public content, not
consent-gated -- so no API round trip is needed at all when it's present.
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
from app.workers.tasks import process_instagram_comment as mod
from app.workers.tasks.process_instagram_comment import process_instagram_comment


class _NoCloseSessionWrapper:
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


def _make_ig_integration(db, tenant_id, ig_account_id="ig-biz-001"):
    integration = Integration(
        id=str(uuid.uuid4()), tenant_id=tenant_id, kind="instagram", status="active",
        credentials_kms_blob=encrypt_credentials({"access_token": "tok"}),
        config={"instagram_business_account_id": ig_account_id},
    )
    db.add(integration)
    db.flush()
    return integration


def _payload(sender_id="929817850128977", comment_id="c1", username=""):
    return {
        "ig_account_id": "ig-biz-001",
        "sender_id": sender_id,
        "comment_id": comment_id,
        "text": "how much?",
        "media_id": "media-1",
        "media_ad_id": "",
        "media_ad_title": "",
        "sender_username": username,
    }


def test_new_guest_uses_username_directly_no_backfill_queued(db):
    tenant = _make_tenant(db)
    _make_ig_integration(db, tenant.id)
    db.commit()

    with patch.object(mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch("app.workers.tasks.process_instagram_dm.backfill_instagram_guest_name") as mock_backfill:
        process_instagram_comment.run(_payload(username="life_through_my_lensss"))

    guest = db.query(Guest).filter_by(tenant_id=tenant.id).first()
    assert guest.name == "@life_through_my_lensss"
    mock_backfill.apply_async.assert_not_called()


def test_new_guest_falls_back_to_placeholder_when_no_username(db):
    tenant = _make_tenant(db)
    _make_ig_integration(db, tenant.id)
    db.commit()

    with patch.object(mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)), \
         patch("app.workers.tasks.process_instagram_dm.backfill_instagram_guest_name") as mock_backfill:
        process_instagram_comment.run(_payload(username=""))

    guest = db.query(Guest).filter_by(tenant_id=tenant.id).first()
    assert guest.name.startswith("IG User ")
    mock_backfill.apply_async.assert_called_once()


def test_existing_placeholder_guest_resolved_by_later_comment(db):
    """A guest created earlier via DM (stuck on the numeric placeholder,
    since DM sender profiles are consent-gated) gets resolved immediately
    once they comment -- no need to wait on the doomed API backfill."""
    tenant = _make_tenant(db)
    _make_ig_integration(db, tenant.id)
    sender_id = "929817850128977"
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant.id, name=f"IG User {sender_id[-6:]}", phone="")
    db.add(g)
    db.flush()

    from app.models.guest_identity import GuestIdentity
    gi = GuestIdentity(
        id=str(uuid.uuid4()), tenant_id=tenant.id, guest_id=g.id,
        identity_type="instagram_user_id", identity_value=sender_id, source="instagram",
    )
    db.add(gi)
    db.commit()

    with patch.object(mod, "SessionLocal", return_value=_NoCloseSessionWrapper(db)):
        process_instagram_comment.run(_payload(sender_id=sender_id, username="new_handle"))

    db.refresh(g)
    assert g.name == "@new_handle"
