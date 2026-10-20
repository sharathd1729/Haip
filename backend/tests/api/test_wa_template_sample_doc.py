"""Sample PDF for a template's DOCUMENT header (wa_template_sample_doc + POST /messaging/templates/{id}/sample-document):
a dummy quote / receipt / invoice is drawn with the workspace's seller details, sent to Meta as the header sample and
stored, so the template can be submitted. No guest data is used, and other workspaces' templates are out of reach."""
import os
import uuid
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.api.v1.endpoints.messaging import TemplateStatus, WATemplate
from app.core.encryption import encrypt_credentials
from app.core.security import create_access_token
from app.models.integration import Integration
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import wa_booking_pack
from app.services import wa_template_sample_doc as sample_doc

DOC_HEADER = {"type": "HEADER", "format": "DOCUMENT"}
BODY = {"type": "BODY", "text": "Hi {{1}}, your invoice.", "example": {"body_text": [["Kiran"]]}}


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _connect_whatsapp(db, tenant_id):
    db.add(Integration(id=str(uuid.uuid4()), tenant_id=tenant_id, kind="whatsapp_meta", status="active",
                       config={"waba_id": "waba123"}, credentials_kms_blob=encrypt_credentials({"access_token": "tok"})))
    db.commit()


def _headers_for(db, tenant_id, role):
    user = User(id=str(uuid.uuid4()), tenant_id=tenant_id, name="U", email=f"u-{uuid.uuid4().hex[:6]}@test.com",
                hashed_password="x", role=role, is_active=True)
    db.add(user)
    db.commit()
    token = create_access_token({"sub": user.id, "tenant_id": tenant_id, "role": role.value})
    return {"Authorization": f"Bearer {token}"}


def _template(db, tenant_id, name=wa_booking_pack.BOOKING_CONFIRMED, components=None, status=TemplateStatus.DRAFT):
    t = WATemplate(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, language="en", status=status,
                   components=components or [DOC_HEADER, BODY])
    db.add(t)
    db.commit()
    return t


def _post(client, headers, template_id):
    return client.post(f"/api/v1/messaging/templates/{template_id}/sample-document", headers=headers)


# ─── service ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name, kind", [
    (wa_booking_pack.QUOTE_PAYMENT, "quote"),
    (wa_booking_pack.PAYMENT_RECEIVED, "receipt"),
    (wa_booking_pack.BOOKING_CONFIRMED, "invoice"),
    ("summer_quote_v2", "quote"),
    ("my_invoice", "invoice"),
])
def test_each_template_gets_its_kind_of_document(name, kind):
    tenant = Tenant(id="t1", name="Ratha", slug="r", plan="growth",
                    brand_config={"invoice_profile": {"legal_name": "Ratha Caravans", "state_code": "29"}})
    assert sample_doc.document_kind(name) == kind
    with patch("app.services.invoice_profile_service.logo_bytes", return_value=None):
        content, filename = sample_doc.sample_pdf(tenant, name)
    assert content.startswith(b"%PDF") and len(content) > 1000
    assert filename == f"sample-{kind}.pdf"


def test_needs_sample_and_with_handle():
    assert sample_doc.needs_sample([DOC_HEADER, BODY]) is True
    assert sample_doc.needs_sample([BODY]) is False
    original = [DOC_HEADER, BODY]
    out = sample_doc.with_handle(original, "4::h")
    assert out[0]["example"] == {"header_handle": ["4::h"]} and "example" not in original[0]   # a copy, not edited in place
    assert sample_doc.needs_sample(out) is False


# ─── endpoint ────────────────────────────────────────────────────────────────

def test_sample_document_is_sent_to_meta_stored_and_set_on_the_template(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _connect_whatsapp(db, tid)
    t = _template(db, tid)
    with patch("app.services.wa_template_service.upload_sample_to_meta", return_value="4::handle") as meta, \
         patch("app.services.media_storage.upload_wa_template_media", return_value=f"{tid}/wa_templates/s.pdf") as store:
        r = _post(client, _h(tenant_and_user), t.id)
    assert r.status_code == 200, r.text
    content, ctype, filename = meta.call_args.args[1:4]
    assert content.startswith(b"%PDF") and ctype == "application/pdf" and filename == "sample-invoice.pdf"
    assert store.call_args.args[0] == tid
    db.refresh(t)
    assert t.header_media_key == f"{tid}/wa_templates/s.pdf"
    assert t.components[0]["example"] == {"header_handle": ["4::handle"]}
    assert r.json()["header_media_key"] == f"{tid}/wa_templates/s.pdf"


def test_template_without_a_document_header_is_refused(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _connect_whatsapp(db, tid)
    t = _template(db, tid, components=[BODY])
    with patch("app.services.wa_template_service.upload_sample_to_meta") as meta:
        r = _post(client, _h(tenant_and_user), t.id)
    assert r.status_code == 400 and "no document header" in r.json()["detail"]
    meta.assert_not_called()


def test_locked_template_is_refused(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    t = _template(db, tid, status=TemplateStatus.APPROVED)
    assert _post(client, _h(tenant_and_user), t.id).status_code == 409


def test_needs_whatsapp_connected_and_stores_nothing(client, db, tenant_and_user):
    t = _template(db, _tid(tenant_and_user))
    with patch("app.services.media_storage.upload_wa_template_media") as store:
        r = _post(client, _h(tenant_and_user), t.id)
    assert r.status_code == 400 and "not connected" in r.json()["detail"].lower()
    store.assert_not_called()


def test_forbidden_for_a_concierge(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    t = _template(db, tid)
    assert _post(client, _headers_for(db, tid, UserRole.CONCIERGE), t.id).status_code == 403


def test_another_workspaces_template_is_404(client, db, tenant_and_user):
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    t = _template(db, other.id)
    with patch("app.services.wa_template_service.upload_sample_to_meta") as meta:
        assert _post(client, _h(tenant_and_user), t.id).status_code == 404
    meta.assert_not_called()
