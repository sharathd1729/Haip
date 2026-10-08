"""Public API: API-key auth, scopes, bookings, messaging, key management, docs."""
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app.api.v1.endpoints.messaging import TemplateStatus, WATemplate  # noqa: E402
from app.core.database import get_db  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.main import app as main_app  # noqa: E402
from app.models.base import gen_uuid  # noqa: E402
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.property import Property, Stay  # noqa: E402
from app.models.stay_finance import StayAddOn, StayPayment  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402
from app.public_api.app import app as public_app  # noqa: E402
from app.services import api_key_service  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

BASE = "/api/public/v1"
PHONE = "+919876543210"


@pytest.fixture()
def pub(db):
    """Client for the public API sharing the test DB session (the sub-app has its own dependency overrides)."""
    def _db():
        yield db
    public_app.dependency_overrides[get_db] = _db
    main_app.dependency_overrides[get_db] = _db
    with TestClient(main_app) as c:
        yield c
    public_app.dependency_overrides.clear()
    main_app.dependency_overrides.clear()


def _key(db, tenant_id, scopes, **kw):
    row, raw = api_key_service.create_key(db, tenant_id, "Ops platform", scopes, None, kw.get("days"))
    if kw.get("revoked"):
        row.revoked_at = datetime.now(timezone.utc)
    if kw.get("expired"):
        row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    return raw


def _h(raw):
    return {"Authorization": f"Bearer {raw}"}


ALL = ["properties:read", "bookings:read", "messages:read", "messages:send"]


def _stay(db, tid, name="Asha Rao", phone=PHONE):
    prop = Property(id=gen_uuid(), tenant_id=tid, name="Caravan 1", slug=f"c-{uuid.uuid4().hex[:6]}", type="villa", is_active=True)
    guest = Guest(id=gen_uuid(), tenant_id=tid, name=name, phone=phone, email="asha@example.com")
    db.add_all([prop, guest])
    db.flush()
    stay = Stay(id=gen_uuid(), tenant_id=tid, guest_id=guest.id, property_id=prop.id, check_in=date.today() + timedelta(days=5),
                check_out=date.today() + timedelta(days=7), adults=2, status="confirmed", total_amount=10000, channel_source="airbnb")
    db.add(stay)
    db.commit()
    return prop, guest, stay


# ─── Auth ─────────────────────────────────────────────────────────────────────

def test_auth_errors_use_the_public_error_shape(pub, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    r = pub.get(f"{BASE}/properties")
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"

    assert pub.get(f"{BASE}/properties", headers=_h("haip_live_nope")).json()["error"]["code"] == "invalid_api_key"
    assert pub.get(f"{BASE}/properties", headers=_h(tenant_and_user["access_token"])).status_code == 401   # a login JWT is not an API key
    assert pub.get(f"{BASE}/properties", headers=_h(_key(db, tid, ALL, revoked=True))).status_code == 401
    assert pub.get(f"{BASE}/properties", headers=_h(_key(db, tid, ALL, expired=True))).status_code == 401

    narrow = _key(db, tid, ["bookings:read"])
    r = pub.get(f"{BASE}/properties", headers=_h(narrow))
    assert r.status_code == 403 and r.json()["error"]["code"] == "insufficient_scope"
    assert pub.get(f"{BASE}/bookings", headers=_h(narrow)).status_code == 200


def test_validation_errors_name_the_field(pub, db, tenant_and_user):
    raw = _key(db, tenant_and_user["tenant"].id, ALL)
    r = pub.post(f"{BASE}/whatsapp/messages/template", json={"to": PHONE}, headers=_h(raw))
    body = r.json()["error"]
    assert r.status_code == 422 and body["code"] == "validation_error"
    assert any(d["field"] == "template_name" for d in body["details"])


def test_last_used_is_recorded(pub, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    raw = _key(db, tid, ALL)
    pub.get(f"{BASE}/properties", headers=_h(raw))
    from app.models.api_key import ApiKey
    assert db.query(ApiKey).filter_by(tenant_id=tid).first().last_used_at is not None


# ─── Bookings ─────────────────────────────────────────────────────────────────

def test_properties_and_bookings_shape_and_isolation(pub, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    prop, guest, stay = _stay(db, tid)
    db.add(StayAddOn(tenant_id=tid, stay_id=stay.id, name="Bonfire", quantity=2, unit_price=500))
    db.add(StayPayment(tenant_id=tid, stay_id=stay.id, kind="payment", amount=4000, method="upi", reference="UTR1", paid_on=date.today()))
    # another account's booking must never appear
    t2 = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t2)
    db.flush()
    _, _, other = _stay(db, t2.id, name="Stranger", phone="+919811100099")
    raw = _key(db, tid, ALL)
    h = _h(raw)

    props = pub.get(f"{BASE}/properties", headers=h).json()["data"]
    assert [p["id"] for p in props] == [prop.id]

    r = pub.get(f"{BASE}/bookings", headers=h).json()
    assert r["meta"]["total"] == 1
    b = r["data"][0]
    assert b["id"] == stay.id and b["guest"]["phone"] == PHONE and b["channel"] == "airbnb" and b["nights"] == 2
    assert b["financials"] == {"stay_charge": 10000.0, "addons_total": 1000.0, "total": 11000.0, "paid": 4000.0,
                               "outstanding": 7000.0, "payment_status": "partial"}
    assert b["addons"][0]["name"] == "Bonfire" and b["payments"][0]["reference"] == "UTR1"
    assert "internal_notes" not in b

    assert pub.get(f"{BASE}/bookings/{stay.id}", headers=h).json()["data"]["id"] == stay.id
    assert pub.get(f"{BASE}/bookings/{other.id}", headers=h).status_code == 404


def test_booking_filters_and_updated_since_sees_payment_only_changes(pub, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    prop, _, stay = _stay(db, tid)
    h = _h(_key(db, tid, ALL))

    assert pub.get(f"{BASE}/bookings?status=cancelled", headers=h).json()["meta"]["total"] == 0
    assert pub.get(f"{BASE}/bookings?property_id={prop.id}&channel=airbnb", headers=h).json()["meta"]["total"] == 1
    assert pub.get(f"{BASE}/bookings?status=weird", headers=h).status_code == 422
    assert pub.get(f"{BASE}/bookings?check_in_from=not-a-date", headers=h).json()["error"]["code"] == "invalid_parameter"

    # the booking row itself is old; only a payment is new
    old = datetime.now(timezone.utc) - timedelta(days=3)
    db.query(Stay).filter_by(id=stay.id).update({"updated_at": old})
    db.commit()
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert pub.get(f"{BASE}/bookings?updated_since={since}", headers=h).json()["meta"]["total"] == 0
    db.add(StayPayment(tenant_id=tid, stay_id=stay.id, kind="payment", amount=100, method="cash", paid_on=date.today()))
    db.commit()
    assert pub.get(f"{BASE}/bookings?updated_since={since}", headers=h).json()["meta"]["total"] == 1


# ─── Messaging ────────────────────────────────────────────────────────────────

def _template(db, tid, name="arrival_alert", language="en", body="Hi {{1}}, your caravan is ready at {{2}}."):
    t = WATemplate(id=gen_uuid(), tenant_id=tid, name=name, language=language, status=TemplateStatus.APPROVED,
                   components=[{"type": "BODY", "text": body}], meta_template_id="m1")
    db.add(t)
    db.commit()
    return t


def test_send_template_creates_thread_and_is_idempotent(pub, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    _template(db, tid)
    h = _h(_key(db, tid, ALL))
    payload = {"to": "98765 43210", "template_name": "arrival_alert", "variables": ["Asha", "Gate 2"], "local_message_id": "ops-1001"}

    with patch("app.workers.tasks.send_whatsapp.send_whatsapp_template.delay") as dispatch:
        r = pub.post(f"{BASE}/whatsapp/messages/template", json=payload, headers=h)
        assert r.status_code == 202, r.text
        data = r.json()["data"]
        assert data["status"] == "queued" and data["to"] == PHONE and data["local_message_id"] == "ops-1001"
        assert data["text"] == "Hi Asha, your caravan is ready at Gate 2."
        again = pub.post(f"{BASE}/whatsapp/messages/template", json=payload, headers=h)
    assert again.json()["idempotent_replay"] is True and again.json()["data"]["id"] == data["id"]
    assert dispatch.call_count == 1                                   # the retry did not send a second message

    assert db.query(Message).filter_by(tenant_id=tid).count() == 1
    guest = db.query(Guest).filter_by(tenant_id=tid, phone=PHONE).one()
    assert db.query(Conversation).filter_by(tenant_id=tid, guest_id=guest.id, channel=ChannelType.WHATSAPP).count() == 1
    assert pub.get(f"{BASE}/messages/{data['id']}", headers=h).json()["data"]["status"] == "queued"


def test_send_template_validation(pub, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    _template(db, tid)
    _template(db, tid, name="multi", language="en")
    _template(db, tid, name="multi", language="hi")
    h = _h(_key(db, tid, ALL))
    url = f"{BASE}/whatsapp/messages/template"

    def code(body):
        r = pub.post(url, json=body, headers=h)
        return r.status_code, r.json()["error"]["code"]

    assert code({"to": PHONE, "template_name": "nope"}) == (404, "template_not_found")
    assert code({"to": PHONE, "template_name": "arrival_alert", "variables": ["only one"]}) == (422, "variable_mismatch")
    assert code({"to": "12", "template_name": "arrival_alert", "variables": ["a", "b"]}) == (422, "invalid_phone")
    assert code({"to": PHONE, "template_name": "multi", "variables": ["a", "b"]}) == (422, "language_required")

    sender_less = _h(_key(db, tid, ["messages:read"]))
    assert pub.post(url, json={"to": PHONE, "template_name": "arrival_alert"}, headers=sender_less).status_code == 403


def test_templates_listing_reports_variable_counts(pub, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    _template(db, tid)
    draft = WATemplate(id=gen_uuid(), tenant_id=tid, name="draft_one", language="en", status=TemplateStatus.DRAFT, components=[])
    db.add(draft)
    db.commit()
    data = pub.get(f"{BASE}/whatsapp/templates", headers=_h(_key(db, tid, ALL))).json()["data"]
    assert [t["name"] for t in data] == ["arrival_alert"] and data[0]["body_variables"] == 2


def _thread(db, tid, channel=ChannelType.WHATSAPP, inbound_age=timedelta(hours=1), phone=PHONE):
    guest = Guest(id=gen_uuid(), tenant_id=tid, name="Asha", phone=phone)
    db.add(guest)
    db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, channel=channel, is_open=True)
    db.add(conv)
    db.flush()
    msg = Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.INBOUND,
                  channel=channel, body="hello")
    msg.created_at = datetime.now(timezone.utc) - inbound_age
    db.add(msg)
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.OUTBOUND,
                   channel=channel, body="staff only", is_internal=True))
    db.commit()
    return conv


def test_text_requires_open_window(pub, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    h = _h(_key(db, tid, ALL))
    url = f"{BASE}/whatsapp/messages/text"

    r = pub.post(url, json={"to": PHONE, "text": "hi"}, headers=h)                     # nobody has written to us
    assert r.status_code == 422 and r.json()["error"]["code"] == "session_window_closed"

    stale = _thread(db, tid, inbound_age=timedelta(hours=30))
    r = pub.post(url, json={"conversation_id": stale.id, "text": "hi"}, headers=h)
    assert r.status_code == 422 and "template" in r.json()["error"]["message"]

    fresh = _thread(db, tid, phone="+919811100022")
    with patch("app.workers.tasks.send_whatsapp.send_whatsapp.delay") as dispatch:
        r = pub.post(url, json={"to": "+919811100022", "text": "Your cab is outside", "local_message_id": "c1"}, headers=h)
        assert r.status_code == 202 and r.json()["data"]["text"] == "Your cab is outside"
        assert dispatch.call_count == 1
    assert pub.post(url, json={"text": "hi"}, headers=h).json()["error"]["code"] == "missing_target"


def test_instagram_text_channel_rules(pub, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    h = _h(_key(db, tid, ALL))
    url = f"{BASE}/instagram/messages/text"
    wa = _thread(db, tid)
    ig = _thread(db, tid, channel=ChannelType.INSTAGRAM, phone="+919811100033")

    assert pub.post(url, json={"conversation_id": wa.id, "text": "hi"}, headers=h).json()["error"]["code"] == "wrong_channel"
    assert pub.post(url, json={"to": PHONE, "text": "hi"}, headers=h).json()["error"]["code"] == "missing_target"
    with patch("app.workers.tasks.send_instagram_dm.send_instagram_dm.delay") as dispatch:
        r = pub.post(url, json={"conversation_id": ig.id, "text": "Thanks for booking"}, headers=h)
    assert r.status_code == 202 and dispatch.call_count == 1


def test_conversations_lookup_and_messages_exclude_internal_notes(pub, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    h = _h(_key(db, tid, ALL))
    conv = _thread(db, tid)

    found = pub.get(f"{BASE}/conversations", params={"phone": PHONE}, headers=h).json()["data"]
    assert [c["id"] for c in found] == [conv.id] and found[0]["reply_window_open"] is True
    assert pub.get(f"{BASE}/conversations", params={"phone": "+919000000000"}, headers=h).json()["data"] == []

    msgs = pub.get(f"{BASE}/conversations/{conv.id}/messages", headers=h).json()
    assert [m["text"] for m in msgs["data"]] == ["hello"] and msgs["meta"]["total"] == 1


def test_other_accounts_conversation_and_message_are_404(pub, db, tenant_and_user):
    tid = tenant_and_user["tenant"].id
    t2 = Tenant(id=str(uuid.uuid4()), name="O2", slug=f"o2-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t2)
    db.flush()
    foreign = _thread(db, t2.id, phone="+919811100055")
    foreign_msg = db.query(Message).filter_by(conversation_id=foreign.id).first()
    h = _h(_key(db, tid, ALL))
    assert pub.get(f"{BASE}/conversations/{foreign.id}/messages", headers=h).status_code == 404
    assert pub.get(f"{BASE}/messages/{foreign_msg.id}", headers=h).status_code == 404
    assert pub.post(f"{BASE}/whatsapp/messages/text", json={"conversation_id": foreign.id, "text": "x"}, headers=h).status_code == 404


# ─── Key management + docs ────────────────────────────────────────────────────

def test_key_lifecycle_owner_only(pub, db, tenant_and_user):
    owner = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    r = pub.post("/api/v1/api-keys", json={"name": "Ratha ops", "scopes": ["bookings:read"]}, headers=owner)
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["key"].startswith("haip_live_") and created["scopes"] == ["bookings:read"]

    listed = pub.get("/api/v1/api-keys", headers=owner).json()
    assert [k["id"] for k in listed["keys"]] == [created["id"]] and "key" not in listed["keys"][0]
    assert listed["docs_url"].endswith("/api/public/v1/docs")

    assert pub.get(f"{BASE}/bookings", headers=_h(created["key"])).status_code == 200      # the new key works
    assert pub.delete(f"/api/v1/api-keys/{created['id']}", headers=owner).status_code == 204
    assert pub.get(f"{BASE}/bookings", headers=_h(created["key"])).status_code == 401      # and stops working at once

    assert pub.post("/api/v1/api-keys", json={"name": "x", "scopes": ["nope"]}, headers=owner).status_code == 422
    assert pub.post("/api/v1/api-keys", json={"name": "x", "scopes": []}, headers=owner).status_code == 422

    mgr = User(id=str(uuid.uuid4()), tenant_id=tenant_and_user["tenant"].id, name="M", email=f"m-{uuid.uuid4().hex[:6]}@t.com",
               hashed_password="x", role=UserRole.MANAGER, is_active=True)
    db.add(mgr)
    db.commit()
    mh = {"Authorization": "Bearer " + create_access_token({"sub": mgr.id, "tenant_id": mgr.tenant_id, "role": "manager"})}
    assert pub.post("/api/v1/api-keys", json={"name": "x", "scopes": ["bookings:read"]}, headers=mh).status_code == 403
    assert pub.get("/api/v1/api-keys", headers=mh).status_code == 200


def test_docs_and_openapi_are_public_and_list_only_public_endpoints(pub):
    spec = pub.get(f"{BASE}/openapi.json")
    assert spec.status_code == 200
    paths = spec.json()["paths"]
    assert "/bookings" in paths and "/whatsapp/messages/template" in paths
    assert not any(p.startswith("/api/v1") or "auth" in p or "api-keys" in p for p in paths)
    assert "haip_live_" in spec.json()["info"]["description"]
    assert pub.get(f"{BASE}/docs").status_code == 200
    assert pub.get(f"{BASE}/redoc").status_code == 200
