"""WhatsApp template editor + campaign variables: endpoints.

Covers media headers, multiple buttons, editing, resubmitting a rejected
template through Meta's edit call, and campaigns refusing to go out with
template variables nobody mapped.
"""
import os
import uuid
from unittest.mock import patch, MagicMock

import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.api.v1.endpoints.messaging import WATemplate, WACampaign, TemplateStatus
from app.core.encryption import encrypt_credentials
from app.core.security import create_access_token
from app.models.integration import Integration
from app.models.tenant import Tenant
from app.models.user import User, UserRole

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 200
BODY = {"type": "BODY", "text": "Hi {{1}}, welcome to Ratha.", "example": {"body_text": [["Priya"]]}}


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _connect_whatsapp(db, tenant_id):
    db.add(Integration(
        id=str(uuid.uuid4()), tenant_id=tenant_id, kind="whatsapp_meta", status="active",
        config={"waba_id": "waba123"}, credentials_kms_blob=encrypt_credentials({"access_token": "tok"}),
    ))
    db.commit()


def _user_with_role(db, tenant_id, role):
    user = User(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name="U", email=f"u-{uuid.uuid4().hex[:6]}@test.com",
        hashed_password="x", role=role, is_active=True,
    )
    db.add(user)
    db.commit()
    token = create_access_token({"sub": user.id, "tenant_id": tenant_id, "role": role.value})
    return {"Authorization": f"Bearer {token}"}


def _other_tenant(db):
    tenant = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(tenant)
    db.flush()
    return tenant.id, _user_with_role(db, tenant.id, UserRole.OWNER)


def _payload(name="summer_offer", components=None, media_key=None):
    return {"name": name, "language": "en", "category": "MARKETING",
            "components": components or [BODY], "header_media_key": media_key}


def _template(db, tenant_id, status=TemplateStatus.DRAFT, name=None, **kw):
    t = WATemplate(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name or f"t_{uuid.uuid4().hex[:6]}",
                   language="en", status=status, components=[BODY], **kw)
    db.add(t)
    db.commit()
    return t


# ─── create ──────────────────────────────────────────────────────────────────

def test_create_with_image_header_and_several_buttons(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    key = f"{tid}/wa_templates/abc.jpg"
    comps = [
        {"type": "HEADER", "format": "IMAGE", "example": {"header_handle": ["4::h"]}},
        BODY,
        {"type": "BUTTONS", "buttons": [
            {"type": "QUICK_REPLY", "text": "Yes"}, {"type": "QUICK_REPLY", "text": "No"},
            {"type": "URL", "text": "Book", "url": "https://ratha.example/book"},
        ]},
    ]
    with patch("app.services.media_storage.get_presigned_media_url", return_value="https://signed.example/x"):
        r = client.post("/api/v1/messaging/templates", json=_payload(components=comps, media_key=key), headers=_h(tenant_and_user))
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["header_media_key"] == key
    assert data["header_media_url"] == "https://signed.example/x"
    assert data["status"] == "draft"


def test_create_rejects_a_template_with_no_body(client, tenant_and_user):
    r = client.post("/api/v1/messaging/templates",
                    json=_payload(components=[{"type": "FOOTER", "text": "x"}]), headers=_h(tenant_and_user))
    assert r.status_code == 400
    assert "body is required" in r.json()["detail"].lower()


def test_create_media_header_without_a_file_is_rejected(client, tenant_and_user):
    comps = [{"type": "HEADER", "format": "IMAGE", "example": {"header_handle": ["4::h"]}}, BODY]
    r = client.post("/api/v1/messaging/templates", json=_payload(components=comps), headers=_h(tenant_and_user))
    assert r.status_code == 400
    assert "attach the header file" in r.json()["detail"].lower()


def test_create_cannot_use_another_workspaces_file(client, db, tenant_and_user):
    other_tid, _ = _other_tenant(db)
    comps = [{"type": "HEADER", "format": "IMAGE", "example": {"header_handle": ["4::h"]}}, BODY]
    r = client.post("/api/v1/messaging/templates",
                    json=_payload(components=comps, media_key=f"{other_tid}/wa_templates/theirs.jpg"),
                    headers=_h(tenant_and_user))
    assert r.status_code == 400
    assert "doesn't belong" in r.json()["detail"]


def test_create_duplicate_name_is_a_clear_conflict(client, tenant_and_user):
    assert client.post("/api/v1/messaging/templates", json=_payload("dup_name"), headers=_h(tenant_and_user)).status_code == 201
    r = client.post("/api/v1/messaging/templates", json=_payload("dup_name"), headers=_h(tenant_and_user))
    assert r.status_code == 409
    assert "already have a template" in r.json()["detail"]


def test_create_forbidden_for_a_concierge(client, db, tenant_and_user):
    headers = _user_with_role(db, _tid(tenant_and_user), UserRole.CONCIERGE)
    assert client.post("/api/v1/messaging/templates", json=_payload(), headers=headers).status_code == 403


# ─── edit ────────────────────────────────────────────────────────────────────

def test_edit_a_draft(client, db, tenant_and_user):
    tmpl = _template(db, _tid(tenant_and_user))
    new = [{"type": "BODY", "text": "Updated text"}]
    r = client.put(f"/api/v1/messaging/templates/{tmpl.id}",
                   json={"language": "hi", "category": "UTILITY", "components": new}, headers=_h(tenant_and_user))
    assert r.status_code == 200, r.text
    db.refresh(tmpl)
    assert tmpl.components == new and tmpl.language == "hi" and tmpl.category.value == "UTILITY"


def test_edit_a_rejected_template_returns_it_to_draft(client, db, tenant_and_user):
    tmpl = _template(db, _tid(tenant_and_user), status=TemplateStatus.REJECTED, meta_template_id="m1")
    tmpl.rejection_reason = "promotional content"
    db.commit()
    r = client.put(f"/api/v1/messaging/templates/{tmpl.id}",
                   json={"components": [BODY]}, headers=_h(tenant_and_user))
    assert r.status_code == 200
    db.refresh(tmpl)
    assert tmpl.status == TemplateStatus.DRAFT and tmpl.rejection_reason is None
    assert tmpl.meta_template_id == "m1"          # still the same record at Meta


@pytest.mark.parametrize("status", [TemplateStatus.APPROVED, TemplateStatus.PENDING])
def test_approved_and_pending_templates_are_locked(client, db, tenant_and_user, status):
    tmpl = _template(db, _tid(tenant_and_user), status=status)
    r = client.put(f"/api/v1/messaging/templates/{tmpl.id}", json={"components": [BODY]}, headers=_h(tenant_and_user))
    assert r.status_code == 409


def test_edit_validates_the_new_content(client, db, tenant_and_user):
    tmpl = _template(db, _tid(tenant_and_user))
    r = client.put(f"/api/v1/messaging/templates/{tmpl.id}",
                   json={"components": [{"type": "BODY", "text": ""}]}, headers=_h(tenant_and_user))
    assert r.status_code == 400


def test_edit_another_workspaces_template_is_404(client, db, tenant_and_user):
    other_tid, _ = _other_tenant(db)
    tmpl = _template(db, other_tid)
    r = client.put(f"/api/v1/messaging/templates/{tmpl.id}", json={"components": [BODY]}, headers=_h(tenant_and_user))
    assert r.status_code == 404


def test_edit_forbidden_for_a_concierge(client, db, tenant_and_user):
    tmpl = _template(db, _tid(tenant_and_user))
    headers = _user_with_role(db, _tid(tenant_and_user), UserRole.CONCIERGE)
    assert client.put(f"/api/v1/messaging/templates/{tmpl.id}", json={"components": [BODY]}, headers=headers).status_code == 403


# ─── media upload ────────────────────────────────────────────────────────────

def _upload(client, headers, fmt="IMAGE", content=JPEG, ctype="image/jpeg"):
    return client.post("/api/v1/messaging/templates/media", data={"format": fmt},
                       files={"file": ("photo.jpg", content, ctype)}, headers=headers)


def test_media_upload_returns_key_handle_and_preview(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _connect_whatsapp(db, tid)
    with patch("app.services.wa_template_service.upload_sample_to_meta", return_value="4::handle") as meta, \
         patch("app.services.media_storage.upload_wa_template_media", return_value=f"{tid}/wa_templates/k.jpg") as store, \
         patch("app.services.media_storage.get_presigned_media_url", return_value="https://signed.example/k"):
        r = _upload(client, _h(tenant_and_user))
    assert r.status_code == 200, r.text
    assert r.json() == {"format": "IMAGE", "media_key": f"{tid}/wa_templates/k.jpg",
                        "header_handle": "4::handle", "preview_url": "https://signed.example/k"}
    meta.assert_called_once()
    store.assert_called_once()


def test_media_upload_rejects_the_wrong_kind_of_file_before_calling_meta(client, db, tenant_and_user):
    _connect_whatsapp(db, _tid(tenant_and_user))
    with patch("app.services.wa_template_service.upload_sample_to_meta") as meta:
        r = _upload(client, _h(tenant_and_user), content=b"<html>hi</html>")
    assert r.status_code == 400
    meta.assert_not_called()


def test_media_upload_needs_whatsapp_connected(client, tenant_and_user):
    r = _upload(client, _h(tenant_and_user))
    assert r.status_code == 400
    assert "not connected" in r.json()["detail"].lower()


def test_media_upload_meta_failure_stores_nothing(client, db, tenant_and_user):
    from app.services import wa_template_service as wts
    _connect_whatsapp(db, _tid(tenant_and_user))
    with patch("app.services.wa_template_service.upload_sample_to_meta", side_effect=wts.TemplateError("Meta refused the upload: bad")), \
         patch("app.services.media_storage.upload_wa_template_media") as store:
        r = _upload(client, _h(tenant_and_user))
    assert r.status_code == 400
    assert "Meta refused" in r.json()["detail"]
    store.assert_not_called()


def test_media_upload_forbidden_for_a_concierge(client, db, tenant_and_user):
    headers = _user_with_role(db, _tid(tenant_and_user), UserRole.CONCIERGE)
    assert _upload(client, headers).status_code == 403


# ─── submit ──────────────────────────────────────────────────────────────────

def test_a_pending_template_cannot_be_submitted_again(client, db, tenant_and_user):
    _connect_whatsapp(db, _tid(tenant_and_user))
    tmpl = _template(db, _tid(tenant_and_user), status=TemplateStatus.PENDING, meta_template_id="m1")
    assert client.post(f"/api/v1/messaging/templates/{tmpl.id}/submit", headers=_h(tenant_and_user)).status_code == 409


def test_submit_rejects_an_invalid_template_before_calling_meta(client, db, tenant_and_user):
    _connect_whatsapp(db, _tid(tenant_and_user))
    tmpl = _template(db, _tid(tenant_and_user))
    tmpl.components = [{"type": "HEADER", "format": "IMAGE"}, BODY]        # no sample uploaded
    db.commit()
    with patch("httpx.post") as post:
        r = client.post(f"/api/v1/messaging/templates/{tmpl.id}/submit", headers=_h(tenant_and_user))
    assert r.status_code == 400
    post.assert_not_called()


def test_resubmitting_a_rejected_template_edits_the_existing_record_at_meta(client, db, tenant_and_user):
    _connect_whatsapp(db, _tid(tenant_and_user))
    tmpl = _template(db, _tid(tenant_and_user), status=TemplateStatus.REJECTED, meta_template_id="meta-99")
    ok = MagicMock()
    ok.json.return_value = {"success": True}
    with patch("httpx.post", return_value=ok) as post:
        r = client.post(f"/api/v1/messaging/templates/{tmpl.id}/submit", headers=_h(tenant_and_user))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending"
    called_url = post.call_args.args[0]
    assert called_url.endswith("/meta-99") and "message_templates" not in called_url


def test_submitting_a_new_template_still_creates_it(client, db, tenant_and_user):
    _connect_whatsapp(db, _tid(tenant_and_user))
    tmpl = _template(db, _tid(tenant_and_user))
    ok = MagicMock()
    ok.json.return_value = {"id": "meta-1"}
    with patch("httpx.post", return_value=ok) as post:
        r = client.post(f"/api/v1/messaging/templates/{tmpl.id}/submit", headers=_h(tenant_and_user))
    assert r.json()["status"] == "pending" and r.json()["meta_template_id"] == "meta-1"
    assert post.call_args.args[0].endswith("/waba123/message_templates")


# ─── campaign variables ──────────────────────────────────────────────────────

def _campaign_body(template_id, variable_map=None):
    return {"name": "Diwali push", "template_id": template_id, "audience_filter": {}, "variable_map": variable_map or {}}


def test_campaign_needs_every_template_variable_mapped(client, db, tenant_and_user):
    tmpl = _template(db, _tid(tenant_and_user), status=TemplateStatus.APPROVED)
    r = client.post("/api/v1/messaging/campaigns", json=_campaign_body(tmpl.id), headers=_h(tenant_and_user))
    assert r.status_code == 400
    assert "body {{1}}" in r.json()["detail"]

    vmap = {"body": {"1": {"source": "first_name", "fallback": "Guest"}}}
    r = client.post("/api/v1/messaging/campaigns", json=_campaign_body(tmpl.id, vmap), headers=_h(tenant_and_user))
    assert r.status_code == 201, r.text
    assert r.json()["variable_map"] == vmap


def test_campaign_for_a_template_without_variables_needs_no_mapping(client, db, tenant_and_user):
    tmpl = _template(db, _tid(tenant_and_user), status=TemplateStatus.APPROVED)
    tmpl.components = [{"type": "BODY", "text": "No variables here"}]
    db.commit()
    assert client.post("/api/v1/messaging/campaigns", json=_campaign_body(tmpl.id), headers=_h(tenant_and_user)).status_code == 201


def test_campaign_with_another_workspaces_template_is_404(client, db, tenant_and_user):
    other_tid, _ = _other_tenant(db)
    tmpl = _template(db, other_tid, status=TemplateStatus.APPROVED)
    r = client.post("/api/v1/messaging/campaigns", json=_campaign_body(tmpl.id, {"body": {"1": {"source": "name"}}}), headers=_h(tenant_and_user))
    assert r.status_code == 404


def test_launch_is_refused_while_variables_are_unmapped(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    tmpl = _template(db, tid, status=TemplateStatus.APPROVED)
    camp = WACampaign(id=str(uuid.uuid4()), tenant_id=tid, name="c", template_id=tmpl.id, audience_filter={}, variable_map={})
    db.add(camp)
    db.commit()
    with patch("app.workers.tasks.run_campaign.run_campaign.apply_async") as enqueue:
        r = client.post(f"/api/v1/messaging/campaigns/{camp.id}/launch", headers=_h(tenant_and_user))
    assert r.status_code == 400
    enqueue.assert_not_called()


def test_patching_a_campaign_cannot_change_protected_fields(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    camp = WACampaign(id=str(uuid.uuid4()), tenant_id=tid, name="c", audience_filter={})
    db.add(camp)
    db.commit()
    other_tid, _ = _other_tenant(db)
    r = client.patch(f"/api/v1/messaging/campaigns/{camp.id}",
                     json={"name": "renamed", "tenant_id": other_tid, "status": "running", "sent_count": "999"},
                     headers=_h(tenant_and_user))
    assert r.status_code == 200
    db.refresh(camp)
    assert camp.name == "renamed"
    assert camp.tenant_id == tid
    assert camp.status.value == "draft"
    assert camp.sent_count == "0"


def test_patching_another_workspaces_campaign_is_404(client, db, tenant_and_user):
    other_tid, _ = _other_tenant(db)
    camp = WACampaign(id=str(uuid.uuid4()), tenant_id=other_tid, name="theirs", audience_filter={})
    db.add(camp)
    db.commit()
    assert client.patch(f"/api/v1/messaging/campaigns/{camp.id}", json={"name": "x"}, headers=_h(tenant_and_user)).status_code == 404
