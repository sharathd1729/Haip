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
