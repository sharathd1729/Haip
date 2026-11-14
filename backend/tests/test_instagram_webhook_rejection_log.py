"""A rejected Instagram webhook must say which account it was for and whether a saved secret was found,
so 'tried META_APP_SECRET only' can be told apart from a wrong secret."""
import json

import structlog
from structlog.testing import capture_logs

from app.core.config import settings


def test_bad_signature_is_rejected_and_logs_the_account(client, monkeypatch):
    monkeypatch.setattr(settings, "META_APP_SECRET", "some-app-secret")
    body = json.dumps({"object": "instagram", "entry": [{"id": "17841400000000000", "messaging": []}]})

    with capture_logs() as logs:
        r = client.post("/api/v1/webhooks/instagram", content=body,
                        headers={"Content-Type": "application/json", "X-Hub-Signature-256": "sha256=deadbeef"})

    assert r.status_code == 401
    rejected = [l for l in logs if l.get("event") == "instagram_webhook_rejected"]
    assert rejected and rejected[0]["ig_account_id"] == "17841400000000000"
    assert rejected[0]["tenant_secret_found"] is False


def _signed(secret: str, body: str) -> str:
    import hashlib
    import hmac
    return "sha256=" + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


def test_a_dm_signed_by_the_workspaces_own_meta_app_is_accepted(client, db, monkeypatch):
    """Jade (14 Nov): its Facebook page's own Meta app (the WhatsApp one) delivered the DMs, signed with that app's
    secret, and every one was rejected. A secret another workspace saved still never verifies this account."""
    from sqlalchemy.orm import Session as SASession

    from app.core import database
    from app.core.encryption import encrypt_credentials
    from app.models.integration import Integration
    from tests.workers.call_analysis_harness import tenant

    monkeypatch.setattr(settings, "META_APP_SECRET", "server-secret")
    monkeypatch.setattr(database, "SessionLocal", lambda: SASession(bind=db.connection()))
    mine, other = tenant(db), tenant(db)
    ig_id = "17841400000000001"
    db.add_all([
        Integration(tenant_id=mine.id, kind="instagram", status="active",
                    config={"instagram_business_account_id": ig_id},
                    credentials_kms_blob=encrypt_credentials({"app_secret": "ig-app-secret"})),
        Integration(tenant_id=mine.id, kind="whatsapp_meta", status="active",
                    credentials_kms_blob=encrypt_credentials({"app_secret": "jade-own-app-secret"})),
        Integration(tenant_id=other.id, kind="whatsapp_meta", status="active",
                    credentials_kms_blob=encrypt_credentials({"app_secret": "someone-elses-secret"})),
    ])
    db.commit()
    body = json.dumps({"object": "instagram", "entry": [{"id": ig_id, "messaging": []}]})
    post = lambda secret: client.post("/api/v1/webhooks/instagram", content=body, headers={  # noqa: E731
        "Content-Type": "application/json", "X-Hub-Signature-256": _signed(secret, body)})

    assert post("jade-own-app-secret").status_code == 200
    assert post("ig-app-secret").status_code == 200
    assert post("someone-elses-secret").status_code == 401
