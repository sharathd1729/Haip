"""Ops alert delivery (ops_alert_sender), Meta status callbacks, and staff numbers on inbound WhatsApp."""
import uuid
from unittest.mock import patch

import httpx

from app.api.v1.endpoints.messaging import TemplateCategory, TemplateStatus, WATemplate
from app.core.encryption import encrypt_credentials
from app.models.conversation import Message
from app.models.guest import Guest
from app.models.integration import Integration
from app.models.ops import OpsAlertSend
from app.models.user import UserRole
from app.services import ops_alert_sender as sender
from app.services import ops_escalation_service as esc
from app.workers.tasks import whatsapp as wa
from tests.ops_helpers import ist, prop, shift, staff, tenant, user

NOON = ist(2026, 10, 19, 12)


class _FakeAdapter:
    def __init__(self, fail_with=None):
        self.calls, self.fail_with = [], fail_with

    async def send_template(self, **kw):
        self.calls.append(kw)
        if self.fail_with:
            raise self.fail_with
        return {"messages": [{"id": f"wamid.{uuid.uuid4().hex[:10]}"}]}


def _connect(db, tenant_id, approved=True):
    db.add(Integration(tenant_id=tenant_id, kind="whatsapp_meta", status="active", config={"phone_number_id": "123"},
                       credentials_kms_blob=encrypt_credentials({"access_token": "tok"})))
    for name in ("ops_alert_v1", "ops_escalation_v1"):
        db.add(WATemplate(tenant_id=tenant_id, name=name, language="en", category=TemplateCategory.UTILITY,
                          status=TemplateStatus.APPROVED if approved else TemplateStatus.PENDING, components=[]))
    db.commit()


def _setup(db, approved=True):
    t = tenant(db)
    p = prop(db, t.id)
    tech = staff(db, t.id, "Tech", "maintenance")
    boss = staff(db, t.id, "Boss", "ops_manager")
    for wd in range(7):          # on shift whatever day the test runs: failures escalate at the real "now"
        shift(db, t.id, tech.id, "maintenance", wd, 0, 24)
        shift(db, t.id, boss.id, "ops_manager", wd, 0, 24)
    user(db, t.id, UserRole.OWNER)
    _connect(db, t.id, approved)
    item, ids = esc.create_item(db, t.id, title="AC not working", severity="high", duty="maintenance", property_id=p.id,
                                summary="Room\nis hot", now=NOON)
    db.commit()
    return t, item, ids, tech, boss


def test_deliver_sends_template_with_ack_and_decline_payloads(db):
    t, item, ids, tech, _ = _setup(db)
    fake = _FakeAdapter()
    with patch("app.adapters.whatsapp.meta_cloud.get_wa_adapter", return_value=fake):
        assert sender.deliver(db, ids[0], t.id) == []
    send = db.query(OpsAlertSend).filter_by(id=ids[0]).first()
    assert send.status == "sent" and send.wamid.startswith("wamid.")
    call = fake.calls[0]
    assert call["to"] == tech.phone_e164 and call["template_name"] == "ops_alert_v1"
    body, ack, dec = call["components"]
    assert [p["text"] for p in body["parameters"]][:3] == ["HIGH", "AC not working", "Ratha 1"]
    assert body["parameters"][3]["text"] == "Room is hot"                      # newlines are not allowed in parameters
    assert ack["parameters"][0]["payload"] == esc.button_payload(send, "ack")
    assert dec["index"] == "1" and dec["parameters"][0]["payload"].startswith("ops:decline:")


def test_unapproved_template_fails_loudly_and_escalates(db):
    t, item, ids, _, boss = _setup(db, approved=False)
    follow = sender.deliver(db, ids[0], t.id)
    send = db.query(OpsAlertSend).filter_by(id=ids[0]).first()
    assert send.status == "failed" and "not approved" in send.error
    assert item.current_step == 1 and follow                                    # nobody left at step 0 → escalated now
    assert db.query(OpsAlertSend).filter_by(id=follow[0]).first().staff_id == boss.id


def test_meta_rejection_records_reason(db):
    t, item, ids, _, _ = _setup(db)
    req = httpx.Request("POST", "https://graph.facebook.com")
    resp = httpx.Response(400, request=req, json={"error": {"code": 131042, "message": "Business eligibility payment issue"}})
    fake = _FakeAdapter(fail_with=httpx.HTTPStatusError("bad", request=req, response=resp))
    with patch("app.adapters.whatsapp.meta_cloud.get_wa_adapter", return_value=fake):
        sender.deliver(db, ids[0], t.id)
    send = db.query(OpsAlertSend).filter_by(id=ids[0]).first()
    assert send.status == "failed" and "131042" in send.error and "payment method" in send.error


def test_failed_status_callback_escalates(db):
    t, item, ids, _, _ = _setup(db)
    with patch("app.adapters.whatsapp.meta_cloud.get_wa_adapter", return_value=_FakeAdapter()):
        sender.deliver(db, ids[0], t.id)
    send = db.query(OpsAlertSend).filter_by(id=ids[0]).first()
    matched, follow = sender.apply_status_callback(db, t.id, {"id": send.wamid, "status": "delivered"})
    assert matched and send.status == "delivered" and follow == []
    matched, follow = sender.apply_status_callback(db, t.id, {"id": send.wamid, "status": "failed",
                                                              "errors": [{"code": 131026, "title": "Message undeliverable"}]})
    assert matched and send.status == "failed" and follow and item.current_step == 1
    assert sender.apply_status_callback(db, t.id, {"id": "wamid.unknown", "status": "read"}) == (False, [])


def test_deliver_skips_items_already_handled(db):
    t, item, ids, tech, _ = _setup(db)
    esc.acknowledge(db, item, staff_id=tech.id, now=NOON)
    assert sender.deliver(db, ids[0], t.id) == []
    assert db.query(OpsAlertSend).filter_by(id=ids[0]).first().status == "skipped"


def test_deliver_is_tenant_scoped(db):
    t, item, ids, _, _ = _setup(db)
    other = tenant(db)
    assert sender.deliver(db, ids[0], other.id) == []
    assert db.query(OpsAlertSend).filter_by(id=ids[0]).first().status == "queued"


# ── Inbound WhatsApp: staff numbers never become guests ────────────────────

def test_staff_text_never_creates_guest_lead_or_inbox_message(db):
    t, item, ids, tech, _ = _setup(db)
    msg = {"from": tech.phone_e164.lstrip("+"), "id": f"wamid.in.{uuid.uuid4().hex[:8]}", "type": "text",
           "text": {"body": "On my way"}}
    with patch("app.workers.tasks.ops_escalation.queue_delivery"):
        wa._handle_inbound_message(db, t, msg, contacts=[])
    assert db.query(Guest).filter_by(tenant_id=t.id).count() == 0
    assert db.query(Message).filter_by(tenant_id=t.id).count() == 0
    from app.models.ops import OpsEscalationEvent
    assert db.query(OpsEscalationEvent).filter_by(item_id=item.id, event="staff_message").count() == 1


def test_staff_button_tap_acknowledges_through_webhook_path(db):
    t, item, ids, tech, _ = _setup(db)
    send = db.query(OpsAlertSend).filter_by(id=ids[0]).first()
    msg = {"from": tech.phone_e164.lstrip("+"), "id": f"wamid.in.{uuid.uuid4().hex[:8]}", "type": "button",
           "button": {"text": "Acknowledge", "payload": esc.button_payload(send, "ack")}}
    with patch("app.workers.tasks.ops_escalation.queue_delivery"):
        wa._handle_inbound_message(db, t, msg, contacts=[])
    db.refresh(item)
    assert item.status == "acknowledged" and item.acknowledged_by_staff_id == tech.id
    assert db.query(Guest).filter_by(tenant_id=t.id).count() == 0


def test_inactive_staff_number_is_treated_as_a_guest_again(db):
    t, item, ids, tech, _ = _setup(db)
    tech.active = False
    db.commit()
    msg = {"from": tech.phone_e164.lstrip("+"), "id": f"wamid.in.{uuid.uuid4().hex[:8]}", "type": "text",
           "text": {"body": "Hello, I want to book"}}
    with patch("app.services.push_service.send_to_tenant"), patch("app.workers.tasks.concierge_draft.concierge_draft.apply_async", create=True):
        wa._handle_inbound_message(db, t, msg, contacts=[])
    assert db.query(Guest).filter_by(tenant_id=t.id).count() == 1


def test_staff_number_in_another_tenant_is_still_a_guest_here(db):
    t, item, ids, tech, _ = _setup(db)
    other = tenant(db)
    msg = {"from": tech.phone_e164.lstrip("+"), "id": f"wamid.in.{uuid.uuid4().hex[:8]}", "type": "text",
           "text": {"body": "Hi"}}
    with patch("app.services.push_service.send_to_tenant"), patch("app.workers.tasks.concierge_draft.concierge_draft.apply_async", create=True):
        wa._handle_inbound_message(db, other, msg, contacts=[])
    assert db.query(Guest).filter_by(tenant_id=other.id).count() == 1
