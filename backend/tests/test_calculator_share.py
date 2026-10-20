"""POST /calculator/share sends the quote with the async WhatsApp adapter: awaited, with the adapter's real `body` keyword.

It used to call `adapter.send_text(to=..., text=...)` without await: the coroutine was never run (nothing was sent), the wrong
keyword would have failed anyway, and `.get` on the coroutine raised, so the endpoint always answered "error". No real HTTP:
the adapter's network call is mocked.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.core.encryption import encrypt_credentials
from app.models.integration import Integration
from tests.test_business_data import _tenant
from tests.test_increment1_defect_specs import _h, _user
from app.models.user import UserRole

BODY = {"property_id": "p1", "checkin": "2026-11-01", "checkout": "2026-11-03", "adults": 2, "guest_phone": "+919800000777", "guest_name": "Asha"}


def _quote():
    return SimpleNamespace(whatsapp_message=lambda **kw: f"Quote for {kw.get('guest_name')}")


def test_share_awaits_the_adapter_with_the_body_keyword(client, db):
    t = _tenant(db)
    db.add(Integration(id=str(uuid.uuid4()), tenant_id=t.id, kind="whatsapp_meta", status="active", config={},
                       credentials_kms_blob=encrypt_credentials({"phone_number_id": "123", "access_token": "test-token"})))
    db.commit()
    sent = AsyncMock(return_value={"messages": [{"id": "wamid.TEST"}]})
    with patch("app.api.v1.endpoints.calculator.calculator_service.build_quote", return_value=_quote()), \
         patch("app.adapters.whatsapp.meta_cloud.MetaCloudAdapter.send_text", sent):
        res = client.post("/api/v1/calculator/share", json=BODY, headers=_h(_user(db, t.id, UserRole.OWNER)))
    assert res.status_code == 200 and res.json()["status"] == "sent" and res.json()["whatsapp_message_id"] == "wamid.TEST"
    sent.assert_awaited_once_with(to="+919800000777", body="Quote for Asha")


def test_share_without_whatsapp_returns_the_text_to_copy(client, db):
    t = _tenant(db)
    with patch("app.api.v1.endpoints.calculator.calculator_service.build_quote", return_value=_quote()):
        res = client.post("/api/v1/calculator/share", json=BODY, headers=_h(_user(db, t.id, UserRole.OWNER)))
    assert res.json() == {"status": "not_sent", "reason": "WhatsApp integration not connected", "message": "Quote for Asha"}


def test_share_from_another_tenant_never_uses_this_tenants_whatsapp(client, db):
    a, b = _tenant(db), _tenant(db)
    db.add(Integration(id=str(uuid.uuid4()), tenant_id=a.id, kind="whatsapp_meta", status="active", config={},
                       credentials_kms_blob=encrypt_credentials({"phone_number_id": "123", "access_token": "test-token"})))
    db.commit()
    sent = AsyncMock(return_value={"messages": [{"id": "x"}]})
    with patch("app.api.v1.endpoints.calculator.calculator_service.build_quote", return_value=_quote()), \
         patch("app.adapters.whatsapp.meta_cloud.MetaCloudAdapter.send_text", sent):
        res = client.post("/api/v1/calculator/share", json=BODY, headers=_h(_user(db, b.id, UserRole.OWNER)))
    assert res.json()["status"] == "not_sent" and not sent.called
