"""HAIP's own website leads (book-demo / contact): stored first, copied into the sales workspace, owners notified.

The old forms posted to /api/leads/* (no such route), swallowed the error and showed "success": every lead was lost.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.core.security import create_access_token
from app.models.consent import Consent
from app.models.guest import Guest
from app.models.inquiry import Inquiry, InquirySource
from app.models.platform_lead import PlatformLead
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import platform_lead_service

URL = "/api/v1/public/leads"


@pytest.fixture(autouse=True)
def _no_redis_limit_and_no_celery():
    """The middleware limit is tested on its own below; Celery is never reached from a unit test."""
    with patch("app.middleware.rate_limit._check_limit", return_value=(True, 0)), \
         patch("app.workers.tasks.platform_leads.notify_owners.delay") as delay:
        yield delay


@pytest.fixture()
def sales_ws(db, tenant_and_user, monkeypatch):
    tenant = tenant_and_user["tenant"]
    monkeypatch.setattr("app.core.config.settings.PLATFORM_LEADS_TENANT_SLUG", tenant.slug)
    return tenant_and_user


def _other_tenant(db, role=UserRole.OWNER):
    t = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    u = User(id=str(uuid.uuid4()), tenant_id=t.id, name="Other Owner", email=f"o-{uuid.uuid4().hex[:6]}@x.com",
             hashed_password="x", role=role, is_active=True)
    db.add(u)
    db.commit()
    return t, u


def _token(user):
    return {"Authorization": "Bearer " + create_access_token(
        {"sub": user.id, "tenant_id": user.tenant_id, "role": user.role.value})}


def demo(**over):
    body = {
        "kind": "demo", "submission_id": uuid.uuid4().hex, "name": "Asha Rao", "email": "asha@villa.in",
        "phone": "98450 12345", "company": "Asha Villas", "details": {"segment": "villas", "properties": "1-3"},
        "message": "Show the concierge", "consent": True, "notice_version": "web-v1", "website": "",
    }
    body.update(over)
    return body


def test_demo_lead_is_stored_and_becomes_a_workspace_lead(client, db, sales_ws, _no_redis_limit_and_no_celery):
    tenant = sales_ws["tenant"]
    r = client.post(URL, json=demo())
    assert r.status_code == 201, r.text
    lead = db.query(PlatformLead).filter_by(id=r.json()["id"]).one()
    assert lead.phone == "+919845012345" and lead.consent_given and lead.notice_text_hash
    assert lead.routing_status == "routed" and lead.workspace_tenant_id == tenant.id
    inquiry = db.query(Inquiry).filter_by(id=lead.workspace_inquiry_id).one()
    assert inquiry.tenant_id == tenant.id and inquiry.source == InquirySource.WEBSITE
    assert inquiry.custom_fields["platform_lead_ids"] == [lead.id]
    guest = db.query(Guest).filter_by(id=inquiry.guest_id).one()
    assert guest.lead_identified_at is not None          # a usable phone makes it a lead
    consent = db.query(Consent).filter_by(guest_id=guest.id, tenant_id=tenant.id).one()
    assert consent.channel == "web_form" and consent.notice_version == "web-v1"
    _no_redis_limit_and_no_celery.assert_called_once_with(lead.id)


def test_tenant_id_in_the_body_is_ignored(client, db, sales_ws):
    other, _ = _other_tenant(db)
    r = client.post(URL, json=demo(tenant_id=other.id, tenant_slug=other.slug))
    assert r.status_code == 201
    assert db.query(Inquiry).filter_by(tenant_id=other.id).count() == 0
    assert db.query(Inquiry).filter_by(tenant_id=sales_ws["tenant"].id).count() == 1


def test_without_a_sales_workspace_the_lead_is_still_stored(client, db, tenant_and_user, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.PLATFORM_LEADS_TENANT_SLUG", "")
    r = client.post(URL, json=demo())
    assert r.status_code == 201
    lead = db.query(PlatformLead).filter_by(id=r.json()["id"]).one()
    assert lead.routing_status == "not_configured" and lead.workspace_inquiry_id is None


def test_same_submission_twice_is_one_lead(client, db, sales_ws):
    body = demo()
    first = client.post(URL, json=body)
    second = client.post(URL, json=body)
    assert first.status_code == 201 and second.status_code == 200
    assert second.json() == {**first.json(), "duplicate": True}
    assert db.query(PlatformLead).filter_by(submission_id=body["submission_id"]).count() == 1
    assert db.query(Inquiry).filter_by(tenant_id=sales_ws["tenant"].id).count() == 1


def test_second_form_from_the_same_person_joins_their_open_lead(client, db, sales_ws):
    client.post(URL, json=demo())
    client.post(URL, json=demo(kind="contact", message="One more question", company=None))
    inquiries = db.query(Inquiry).filter_by(tenant_id=sales_ws["tenant"].id).all()
    assert len(inquiries) == 1 and len(inquiries[0].custom_fields["platform_lead_ids"]) == 2


def test_honeypot_is_stored_as_spam_and_goes_no_further(client, db, sales_ws, _no_redis_limit_and_no_celery):
    r = client.post(URL, json=demo(website="http://spam.example"))
    assert r.status_code == 201                      # same answer as a real lead: bots learn nothing
    lead = db.query(PlatformLead).filter_by(id=r.json()["id"]).one()
    assert lead.is_spam and lead.routing_status == "spam"
    assert db.query(Inquiry).filter_by(tenant_id=sales_ws["tenant"].id).count() == 0
    _no_redis_limit_and_no_celery.assert_not_called()


@pytest.mark.parametrize("over", [
    {"consent": False},
    {"phone": "12345"},
    {"company": None},
    {"email": "not-an-email"},
    {"name": ""},
    {"submission_id": "bad id!"},
    {"notice_version": "web-v99"},
    {"message": "x" * 2001},
])
def test_invalid_submissions_are_rejected(client, db, sales_ws, over):
    r = client.post(URL, json=demo(**over))
    assert r.status_code == 422, r.text
    assert db.query(PlatformLead).count() == 0


def test_contact_message_without_phone_uses_the_email(client, db, sales_ws):
    r = client.post(URL, json={"kind": "contact", "submission_id": uuid.uuid4().hex, "name": "Ravi",
                               "email": "ravi@hotel.in", "message": "Pricing please", "consent": True,
                               "details": {"topic": "sales"}})
    assert r.status_code == 201, r.text
    lead = db.query(PlatformLead).filter_by(id=r.json()["id"]).one()
    assert lead.routing_status == "routed" and lead.phone is None
    guest = db.query(Guest).join(Inquiry, Inquiry.guest_id == Guest.id).filter(Inquiry.id == lead.workspace_inquiry_id).one()
    assert guest.lead_identified_at is None          # no phone: a contact, not yet a lead (CLAUDE.md lead definition)


def test_per_visitor_limit_holds_without_redis(client, db, sales_ws, monkeypatch):
    monkeypatch.setattr(platform_lead_service, "MAX_PER_IP_PER_HOUR", 2)
    codes = [client.post(URL, json=demo(), headers={"X-Forwarded-For": "203.0.113.9"}).status_code for _ in range(3)]
    assert codes == [201, 201, 429]
    assert client.post(URL, json=demo(), headers={"X-Forwarded-For": "203.0.113.10"}).status_code == 201


def test_middleware_limit_applies_to_public_forms(client, db, sales_ws):
    with patch("app.middleware.rate_limit._check_limit", return_value=(False, 30)) as check:
        r = client.post(URL, json=demo())
    assert r.status_code == 429 and r.headers["Retry-After"] == "30"
    assert check.call_args.args[1].endswith(":public:lead") and check.call_args.args[2] == 10


def test_oversized_body_is_refused(client, db, sales_ws):
    r = client.post(URL, content=b'{"kind":"demo","pad":"' + b"x" * 17000 + b'"}',
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_routing_failure_keeps_the_lead(client, db, sales_ws, monkeypatch):
    # The failure happens before any write, so the rollback has nothing to undo. On SQLite a real rollback would
    # also erase this test's own rows (conftest), which PostgreSQL's savepoint-per-test mode does not.
    monkeypatch.setattr(db, "rollback", lambda: None)
    with patch("app.services.platform_lead_service._create_inquiry", side_effect=RuntimeError("boom")):
        r = client.post(URL, json=demo())
    assert r.status_code == 201
    lead = db.query(PlatformLead).filter_by(id=r.json()["id"]).one()
    assert lead.routing_status == "failed" and "boom" in lead.routing_error


# ── notification (Celery task body) ──────────────────────────────────────────

def test_notify_emails_and_pushes_the_owners_once(client, db, sales_ws):
    r = client.post(URL, json=demo())
    lead_id = r.json()["id"]
    with patch("app.services.email_service.send_platform_lead_email", new=AsyncMock(return_value=True)) as mail, \
         patch("app.services.push_service.send_to_tenant") as push:
        first = platform_lead_service.notify(db, lead_id)
        again = platform_lead_service.notify(db, lead_id)
    assert first["status"] == "notified" and first["emails_sent"] == 1
    assert again["status"] == "skipped"
    assert mail.await_args.kwargs["to_email"] == sales_ws["user"].email
    assert push.call_args.kwargs["user_id"] == sales_ws["user"].id


# ── owner-only list ──────────────────────────────────────────────────────────

def test_sales_workspace_owner_lists_leads(client, db, sales_ws):
    client.post(URL, json=demo())
    client.post(URL, json=demo(website="bot"))
    r = client.get("/api/v1/platform-leads", headers={"Authorization": f"Bearer {sales_ws['access_token']}"})
    assert r.status_code == 200
    assert r.json()["count"] == 1 and r.json()["items"][0]["name"] == "Asha Rao"
    r = client.get("/api/v1/platform-leads?include_spam=true", headers={"Authorization": f"Bearer {sales_ws['access_token']}"})
    assert r.json()["count"] == 2


def test_list_forbidden_for_a_manager_of_the_sales_workspace(client, db, sales_ws):
    manager = User(id=str(uuid.uuid4()), tenant_id=sales_ws["tenant"].id, name="M", email=f"m-{uuid.uuid4().hex[:6]}@x.com",
                   hashed_password="x", role=UserRole.MANAGER, is_active=True)
    db.add(manager)
    db.commit()
    assert client.get("/api/v1/platform-leads", headers=_token(manager)).status_code == 403


def test_list_forbidden_for_another_workspaces_owner(client, db, sales_ws):
    client.post(URL, json=demo())
    _, other_owner = _other_tenant(db)
    assert client.get("/api/v1/platform-leads", headers=_token(other_owner)).status_code == 403


def test_list_forbidden_when_no_sales_workspace_is_configured(client, db, tenant_and_user, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.PLATFORM_LEADS_TENANT_SLUG", "")
    r = client.get("/api/v1/platform-leads", headers={"Authorization": f"Bearer {tenant_and_user['access_token']}"})
    assert r.status_code == 403
