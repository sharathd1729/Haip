"""Team alerts (P3/P4): the severity ladder read from the work queue, who gets what, quiet hours + morning summary, staff
button taps, delivery receipts, opt-in, and the sender_kind contact rule. Meta and push are faked; nothing is sent."""
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.api.v1.endpoints.messaging import TemplateCategory, TemplateStatus, WATemplate
from app.core.security import create_access_token, get_password_hash
from app.models.audit_event import AuditEvent
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.inquiry import Inquiry
from app.models.lead_workflow import PlaybookAction, PlaybookRun
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import lead_alert_service as alerts
from app.services import lead_playbook_catalog as cat
from app.services import lead_playbook_settings as pb_settings
from app.services import wa_lead_pack as pack
from app.services.work_queue_service import human_touch

API = "/api/v1"
NOW = datetime(2026, 10, 20, 6, 0, tzinfo=timezone.utc)      # 11:30 IST: outside quiet hours
NIGHT = datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc)   # 23:30 IST: quiet hours


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


class _FakeMeta:
    def __init__(self):
        self.templates, self.texts = [], []

    async def send_template(self, to, template_name, language_code="en", components=None):
        self.templates.append({"to": to, "template": template_name, "components": components})
        return {"messages": [{"id": f"wamid.{len(self.templates)}"}]}

    async def send_text(self, to, body):
        self.texts.append({"to": to, "body": body})
        return {"messages": [{"id": "wamid.text"}]}


@contextmanager
def _fakes():
    meta = _FakeMeta()
    with patch("app.services.lead_alert_sender._adapter", return_value=meta), \
         patch("app.services.lead_alert_sender.wa_credentials", return_value=("pnid", "tok")), \
         patch("app.services.push_service.send_to_tenant") as push:
        yield meta, push


def _user(db, tid, role, phone=None, opted=True, name=None):
    u = User(id=str(uuid.uuid4()), tenant_id=tid, name=name or f"{role.value.title()} Person", role=role, is_active=True,
             email=f"{uuid.uuid4().hex[:8]}@t.com", hashed_password=get_password_hash("pw-123456789"), phone=phone,
             whatsapp_alerts_opt_in_at=NOW if opted and phone else None)
    db.add(u)
    db.commit()
    return u


def _setup(db, tid, *keys, approve=True):
    tenant = db.query(Tenant).filter_by(id=tid).first()
    pb_settings.update(db, tenant, None, {"playbooks": {k: {"enabled": True} for k in keys}})
    if approve:
        for name in (pack.STAFF_ALERT, pack.STAFF_ESCALATION, pack.STAFF_DIGEST):
            db.add(WATemplate(tenant_id=tid, name=name, language="en", category=TemplateCategory.UTILITY,
                              status=TemplateStatus.APPROVED, components=[dict(c) for c in pack.BY_NAME[name]["components"]]))
    db.commit()
    return tenant


def _item(kind="new_lead", severity="late", owner=None, guest_id="g1", inquiry_id=None, since=None):
    return {"kind": kind, "severity": severity, "title": "Kiran Rao", "detail": "Asked about Coorg", "facts": ["Coorg", "6 guests"],
            "guest_id": guest_id, "inquiry_id": inquiry_id, "owner_id": owner.id if owner else None,
            "owner_name": owner.name if owner else None, "since": (since or NOW - timedelta(minutes=20)).isoformat()}


def _tick(db, tenant, items, now=NOW):
    with patch("app.services.work_queue_service.build", return_value={"items": items}):
        return alerts.tick(db, tenant, now)


def _acts(db, tid, **kw):
    return db.query(PlaybookAction).filter_by(tenant_id=tid, **kw).order_by(PlaybookAction.created_at).all()


# ── The ladder ──────────────────────────────────────────────────────────────

def test_off_until_switched_on(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    tenant = db.query(Tenant).filter_by(id=tid).first()
    assert _tick(db, tenant, [_item()])["status"] == "off"


def test_each_level_fires_once_and_climbs_to_managers_then_owners(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    tenant = _setup(db, tid, cat.NEW_LEAD_ALERT)
    owner = tenant_and_user["user"]
    owner.phone, owner.whatsapp_alerts_opt_in_at = "+919800000001", NOW
    agent = _user(db, tid, UserRole.CONCIERGE, phone="+919800000002", name="Asha Kumar")
    manager = _user(db, tid, UserRole.MANAGER, phone="+919800000003")
    with _fakes() as (meta, push):
        _tick(db, tenant, [_item(owner=agent)])
        _tick(db, tenant, [_item(owner=agent)])                        # same level again: nothing new
        assert [t["to"] for t in meta.templates] == ["+919800000002"]
        assert meta.templates[0]["template"] == pack.STAFF_ALERT
        payloads = [c["parameters"][0]["payload"] for c in meta.templates[0]["components"] if c["type"] == "button"]
        assert payloads[0].startswith("la:") and payloads[0].endswith(":ack") and payloads[1].endswith(":take")
        _tick(db, tenant, [_item(owner=agent, severity="urgent")])
        _tick(db, tenant, [_item(owner=agent, severity="critical")])
    assert [t["to"] for t in meta.templates] == ["+919800000002", "+919800000003", "+919800000001"]
    assert [t["template"] for t in meta.templates[1:]] == [pack.STAFF_ESCALATION] * 2
    body = meta.templates[2]["components"][0]["parameters"]
    assert [p["text"] for p in body][:2] == ["Critical", "Kiran, new lead"] and "+91" not in str(body)
    assert push.call_count == 3
    run = db.query(PlaybookRun).filter_by(tenant_id=tid, playbook_key=cat.NEW_LEAD_ALERT).one()
    assert run.step == 3 and run.status == "watching"


def test_handled_item_closes_and_unowned_starts_with_managers(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    tenant = _setup(db, tid, cat.NEW_LEAD_ALERT, cat.SLA_ESCALATION)
    manager = _user(db, tid, UserRole.MANAGER, phone="+919800000003")
    with _fakes() as (meta, _push):
        _tick(db, tenant, [_item(), _item(kind="reply", guest_id="g2")])
        out = _tick(db, tenant, [])
    assert {t["to"] for t in meta.templates} == {"+919800000003"} and len(meta.templates) == 2
    assert out["closed"] == 2
    assert {r.status for r in db.query(PlaybookRun).filter_by(tenant_id=tid).all()} == {"done"}
    assert manager.id in {a.recipient_user_id for a in _acts(db, tid, action="staff_wa")}


def test_not_opted_in_gets_push_only_and_unapproved_template_fails_loudly(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    tenant = _setup(db, tid, cat.NEW_LEAD_ALERT, approve=False)
    agent = _user(db, tid, UserRole.CONCIERGE, phone="+919800000002", opted=False)
    manager = _user(db, tid, UserRole.MANAGER, phone="+919800000003")
    with _fakes() as (meta, push):
        _tick(db, tenant, [_item(owner=agent)])
        _tick(db, tenant, [_item(owner=agent, severity="urgent")])
    assert meta.templates == []
    assert push.call_count == 2                                         # agent pushed, then the manager
    failed = _acts(db, tid, action="staff_wa")
    assert len(failed) == 1 and failed[0].recipient_user_id == manager.id and failed[0].status == "failed"
    assert "not approved" in failed[0].reason


def test_quiet_hours_hold_then_one_morning_summary(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    tenant = _setup(db, tid, cat.NEW_LEAD_ALERT)
    agent = _user(db, tid, UserRole.CONCIERGE, phone="+919800000002")
    night_item = _item(owner=agent, since=NIGHT - timedelta(minutes=20))
    with _fakes() as (meta, push):
        out = _tick(db, tenant, [night_item], now=NIGHT)
        assert out["quiet"] is True and meta.templates == [] and push.call_count == 0
        assert [a.status for a in _acts(db, tid)] == ["held"]
        morning = NIGHT + timedelta(hours=9)                            # 08:30 IST
        _tick(db, tenant, [{**night_item, "severity": "critical"}], now=morning)
        _tick(db, tenant, [{**night_item, "severity": "critical"}], now=morning + timedelta(minutes=2))
    digests = [t for t in meta.templates if t["template"] == pack.STAFF_DIGEST]
    assert len(digests) == 1 and [b for b in digests[0]["components"] if b["type"] == "button"] == []
    assert not _acts(db, tid, status="held")


# ── Staff replies, receipts, the webhook ────────────────────────────────────

def test_acknowledge_and_take_from_the_right_number_only(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    tenant = _setup(db, tid, cat.NEW_LEAD_ALERT)
    agent = _user(db, tid, UserRole.CONCIERGE, phone="+919800000002")
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Kiran Rao", phone="+919876543210")
    db.add(guest)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id)
    db.add(inq)
    db.commit()
    with _fakes() as (meta, _push):
        _tick(db, tenant, [_item(guest_id=guest.id, inquiry_id=inq.id)])         # unowned: managers -> owners (none: owner)
        owner = tenant_and_user["user"]
        action = _acts(db, tid, action="push")[0]
        assert action.recipient_user_id == owner.id
        owner.phone, owner.whatsapp_alerts_opt_in_at = "+919800000001", NOW
        db.commit()
        assert alerts.handle_staff_inbound(db, tid, "+919800000099", f"la:{action.id}:take") == "wrong_person"
        assert alerts.handle_staff_inbound(db, tid, "+919800000001", "la:nope:ack") == "unknown"
        assert alerts.handle_staff_inbound(db, tid, "+919800000001", f"la:{action.id}:take") == "taken"
    db.refresh(inq)
    assert inq.assigned_to == owner.id and inq.assignment_method == "claimed"
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="workflows.lead_claimed").count() == 1
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="workflows.alert_acknowledged").count() == 1
    assert "is now yours" in meta.texts[-1]["body"]
    assert agent.id != inq.assigned_to


def test_staff_tap_on_the_webhook_never_becomes_a_guest(db, tenant_and_user):
    from app.workers.tasks.whatsapp import _handle_inbound_message
    tid = _tid(tenant_and_user)
    tenant = _setup(db, tid, cat.NEW_LEAD_ALERT)
    _user(db, tid, UserRole.MANAGER, phone="+919800000003")
    before = db.query(Guest).filter_by(tenant_id=tid).count()
    msg = {"from": "919800000003", "id": "wamid.staff1", "type": "button",
           "button": {"text": pack.BTN_ACK, "payload": "la:missing:ack"}}
    with _fakes(), patch("app.core.cache.get_cached", return_value=None), patch("app.core.cache.set_cached"):
        _handle_inbound_message(db, tenant, msg, [])
        _handle_inbound_message(db, tenant, {**msg, "id": "wamid.staff2", "type": "text", "text": {"body": "ok"}}, [])
    assert db.query(Guest).filter_by(tenant_id=tid).count() == before
    assert db.query(Message).filter_by(tenant_id=tid).count() == 0


def test_failed_receipt_marks_failed_and_pushes_once(db, tenant_and_user):
    from app.services import lead_alert_sender
    tid = _tid(tenant_and_user)
    tenant = _setup(db, tid, cat.NEW_LEAD_ALERT)
    _user(db, tid, UserRole.MANAGER, phone="+919800000003")
    with _fakes() as (_meta, push):
        _tick(db, tenant, [_item()])
        wa = _acts(db, tid, action="staff_wa")[0]
        status = {"id": wa.wa_message_id, "status": "failed", "errors": [{"code": 131026, "title": "Undeliverable"}]}
        assert lead_alert_sender.apply_status_callback(db, tid, status)
        assert lead_alert_sender.apply_status_callback(db, tid, status)
        assert not lead_alert_sender.apply_status_callback(db, tid, {"id": "wamid.someone-else", "status": "read"})
    db.refresh(wa)
    assert wa.status == "failed" and "131026" in wa.reason
    assert push.call_count == 2                                         # the alert's push + one fallback


# ── Endpoints ───────────────────────────────────────────────────────────────

def test_opt_in_ack_and_recipients_endpoints(client, db, tenant_and_user, capabilities_seeded):
    tid = _tid(tenant_and_user)
    owner_h = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    r = client.put(f"{API}/workflows/alerts/me", headers=owner_h, json={"enabled": True})
    assert r.status_code == 422                                         # no phone on the profile yet
    tenant_and_user["user"].phone = "+919800000001"
    db.commit()
    r = client.put(f"{API}/workflows/alerts/me", headers=owner_h, json={"enabled": True})
    assert r.status_code == 200 and r.json()["whatsapp_opt_in"] is True
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="workflows.whatsapp_alerts_opted_in").count() == 1
    r = client.get(f"{API}/workflows/alerts/recipients", headers=owner_h)
    assert r.status_code == 200 and r.json()["people"][0]["channel"] == "whatsapp"

    agent = _user(db, tid, UserRole.CONCIERGE)
    agent_h = {"Authorization": f"Bearer {create_access_token({'sub': agent.id, 'tenant_id': tid, 'role': 'concierge'})}"}
    assert client.get(f"{API}/workflows/alerts/recipients", headers=agent_h).status_code == 403
    assert client.get(f"{API}/workflows/alerts/me", headers=agent_h).json() == {"whatsapp_opt_in": False, "has_phone": False}
    action = PlaybookAction(tenant_id=tid, playbook_key=cat.NEW_LEAD_ALERT, action="push", status="done",
                            recipient_user_id=tenant_and_user["user"].id, payload={})
    db.add(action)
    db.commit()
    assert client.post(f"{API}/workflows/alerts/{action.id}/ack", headers=agent_h).status_code == 404   # not theirs
    r = client.post(f"{API}/workflows/alerts/{action.id}/ack", headers=owner_h)
    assert r.status_code == 200 and r.json()["acked_at"]


# ── The contact rule: what is NOT a person's contact ────────────────────────

def test_campaign_booking_and_mirrored_history_are_not_contact(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Meera", phone="+919876500011")
    db.add(guest)
    db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv)
    db.flush()
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    for kind in ("campaign", "system", "bridge_history", "playbook"):
        db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.OUTBOUND,
                       channel=ChannelType.WHATSAPP, body="x", sender_kind=kind, was_approved=True))
    db.commit()
    assert guest.id not in human_touch(db, tid, {guest.id: since})[0]
    db.add(Message(id=str(uuid.uuid4()), tenant_id=tid, conversation_id=conv.id, direction=MessageDirection.OUTBOUND,
                   channel=ChannelType.WHATSAPP, body="Hi from my phone", sender_kind="bridge_live"))
    db.commit()
    assert guest.id in human_touch(db, tid, {guest.id: since})[0]


def test_waited_and_quiet_hours_helpers():
    assert alerts.waited(NOW - timedelta(minutes=25), NOW) == "25 min"
    assert alerts.waited(NOW - timedelta(minutes=130), NOW) == "2 h 10 min"
    assert alerts.waited(NOW - timedelta(hours=30), NOW) == "1 day"
    tenant = Tenant(id="t", name="T", slug="t", plan="growth")
    assert alerts.in_quiet_hours(tenant, NIGHT) is True and alerts.in_quiet_hours(tenant, NOW) is False


def test_real_queue_new_lead_reaches_its_owner(db, tenant_and_user):
    """No fake queue: a lead identified 20 minutes ago that nobody has contacted is "late" in work_queue_service.build,
    and its owner gets the alert."""
    tid = _tid(tenant_and_user)
    tenant = _setup(db, tid, cat.NEW_LEAD_ALERT)
    agent = _user(db, tid, UserRole.CONCIERGE, phone="+919800000002")
    now = datetime.now(timezone.utc)
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tid, name="Kiran Rao", phone="+919876543210",
                  lead_identified_at=now - timedelta(minutes=20))
    db.add(guest)
    db.flush()
    db.add(Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, assigned_to=agent.id))
    db.commit()
    with _fakes() as (meta, _push), patch("app.core.tenant_tz.get_tz", return_value=timezone.utc):
        tenant.brand_config = {**tenant.brand_config, "lead_playbooks": {**tenant.brand_config["lead_playbooks"],
                                                                         "quiet_start_hour": 0, "quiet_end_hour": 0}}
        db.commit()
        out = alerts.tick(db, tenant)
    assert out["fired"] == 1
    assert [t["to"] for t in meta.templates] == ["+919800000002"]
