"""Start on WhatsApp (POST /guests/{id}/whatsapp/start) for a guest who gave their number on Instagram, the no-answer
playbook for such a guest, a late AI "no answer" verdict, and Meta's undeliverable receipts in plain words.
No real sends: the Celery send tasks are patched."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.api.v1.endpoints.messaging import TemplateCategory, TemplateStatus, WATemplate
from app.core.security import create_access_token, get_password_hash
from app.models.audit_event import AuditEvent
from app.models.call import Call, CallDirection
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState
from app.models.guest import Guest
from app.models.guest_identity import GuestIdentity
from app.models.inquiry import Inquiry
from app.models.lead_workflow import PlaybookAction, PlaybookRun
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.services import lead_playbook_catalog as cat
from app.services import lead_playbook_engine as engine
from app.services import lead_playbook_settings as pb_settings
from app.services import wa_delivery_errors
from app.services import wa_lead_pack as pack

pytestmark = pytest.mark.usefixtures("capabilities_seeded")
PHONE = "+919876501234"


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _h(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _instagram_lead(db, tenant_id, phone=PHONE):
    """A guest who wrote on Instagram and typed their number there: phone set, Instagram thread only."""
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name="Neha Test", phone=phone)
    db.add(guest)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id)
    ig = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.INSTAGRAM, is_open=True)
    db.add_all([inq, ig])
    db.commit()
    return guest, inq, ig


def _template(db, tenant_id, name="lead_hello", status=TemplateStatus.APPROVED):
    t = WATemplate(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name, language="en", status=status,
                   components=[{"type": "BODY", "text": "Hi {{1}}, this is Ratha on WhatsApp."}])
    db.add(t)
    db.commit()
    return t


def _wa_convs(db, tenant_id, guest_id):
    return db.query(Conversation).filter_by(tenant_id=tenant_id, guest_id=guest_id, channel=ChannelType.WHATSAPP).all()


def _start(client, tu, guest_id, template_id, headers=None, **kw):
    with patch("app.workers.tasks.send_whatsapp.send_whatsapp_template.delay") as delay:
        resp = client.post(f"/api/v1/guests/{guest_id}/whatsapp/start",
                           json={"template_id": template_id, "variables": ["Neha"], **kw}, headers=headers or _h(tu))
    return resp, delay


# ── POST /guests/{id}/whatsapp/start ────────────────────────────────────────

def test_start_opens_whatsapp_thread_adds_signal_and_queues_template(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    guest, inq, _ig = _instagram_lead(db, tid)
    tmpl = _template(db, tid)
    resp, delay = _start(client, tenant_and_user, guest.id, tmpl.id, inquiry_id=inq.id)
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert out["created"] is True and out["message"]["body"] == "Hi Neha, this is Ratha on WhatsApp."
    convs = _wa_convs(db, tid, guest.id)
    assert len(convs) == 1 and convs[0].id == out["conversation_id"] and convs[0].inquiry_id == inq.id
    msg = db.query(Message).filter_by(id=out["message"]["id"]).one()
    assert msg.delivery_state == MessageDeliveryState.QUEUED and msg.sender_kind == "human"
    assert msg.channel_metadata["template_name"] == "lead_hello"
    delay.assert_called_once()
    assert delay.call_args.kwargs["template_name"] == "lead_hello" and delay.call_args.kwargs["variables"] == ["Neha"]
    assert db.query(GuestIdentity).filter_by(tenant_id=tid, guest_id=guest.id, identity_type="whatsapp_number").count() == 1
    audit = db.query(AuditEvent).filter_by(tenant_id=tid, action="conversation.whatsapp_started").one()
    assert audit.target_id == out["conversation_id"]


def test_start_reuses_open_whatsapp_thread_and_never_creates_a_second(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    guest, _inq, _ig = _instagram_lead(db, tid)
    tmpl = _template(db, tid)
    first, _ = _start(client, tenant_and_user, guest.id, tmpl.id)
    second, _ = _start(client, tenant_and_user, guest.id, tmpl.id)
    assert first.status_code == second.status_code == 201
    assert second.json()["created"] is False
    assert second.json()["conversation_id"] == first.json()["conversation_id"]
    assert len(_wa_convs(db, tid, guest.id)) == 1
    assert db.query(GuestIdentity).filter_by(tenant_id=tid, guest_id=guest.id, identity_type="whatsapp_number").count() == 1


def test_start_reuses_an_existing_open_whatsapp_conversation(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    guest, _inq, _ig = _instagram_lead(db, tid)
    wa = Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(wa)
    db.commit()
    resp, _ = _start(client, tenant_and_user, guest.id, _template(db, tid).id)
    assert resp.status_code == 201 and resp.json()["conversation_id"] == wa.id
    assert len(_wa_convs(db, tid, guest.id)) == 1


def test_start_same_idempotency_key_sends_once(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    guest, _inq, _ig = _instagram_lead(db, tid)
    tmpl = _template(db, tid)
    h = {**_h(tenant_and_user), "Idempotency-Key": str(uuid.uuid4())}
    with patch("app.workers.tasks.send_whatsapp.send_whatsapp_template.delay") as delay:
        a = client.post(f"/api/v1/guests/{guest.id}/whatsapp/start", json={"template_id": tmpl.id, "variables": ["N"]}, headers=h)
        b = client.post(f"/api/v1/guests/{guest.id}/whatsapp/start", json={"template_id": tmpl.id, "variables": ["N"]}, headers=h)
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["message"]["id"] == b.json()["message"]["id"]
    delay.assert_called_once()


def test_start_bad_number_is_422_and_nothing_written(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    guest, _inq, _ig = _instagram_lead(db, tid, phone="12345")
    resp, delay = _start(client, tenant_and_user, guest.id, _template(db, tid).id)
    assert resp.status_code == 422
    assert "isn't a valid WhatsApp number" in resp.json()["detail"]
    assert _wa_convs(db, tid, guest.id) == []
    delay.assert_not_called()


def test_start_refuses_unapproved_template(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    guest, _inq, _ig = _instagram_lead(db, tid)
    resp, delay = _start(client, tenant_and_user, guest.id, _template(db, tid, status=TemplateStatus.PENDING).id)
    assert resp.status_code == 422 and _wa_convs(db, tid, guest.id) == []
    delay.assert_not_called()


def test_start_never_writes_into_a_personal_bridge_thread(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    guest, _inq, _ig = _instagram_lead(db, tid)
    db.add(Conversation(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True,
                        source="personal_bridge"))
    db.commit()
    resp, delay = _start(client, tenant_and_user, guest.id, _template(db, tid).id)
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "personal_bridge_read_only"
    assert db.query(Message).filter_by(tenant_id=tid).count() == 0
    delay.assert_not_called()


def test_start_wrong_role_is_403(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    guest, _inq, _ig = _instagram_lead(db, tid)
    tmpl = _template(db, tid)
    viewer = User(id=str(uuid.uuid4()), tenant_id=tid, name="Viewer", email=f"v-{uuid.uuid4().hex[:6]}@t.com",
                  hashed_password=get_password_hash("x" * 12), role=UserRole.READ_ONLY, is_active=True)
    db.add(viewer)
    db.commit()
    token = create_access_token({"sub": viewer.id, "tenant_id": tid, "role": viewer.role.value})
    resp, delay = _start(client, tenant_and_user, guest.id, tmpl.id, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403
    delay.assert_not_called()


def test_start_other_tenants_guest_is_404(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    guest, _inq, _ig = _instagram_lead(db, other.id)
    resp, delay = _start(client, tenant_and_user, guest.id, _template(db, tid).id)
    assert resp.status_code == 404
    assert _wa_convs(db, other.id, guest.id) == []
    delay.assert_not_called()


def test_send_template_on_instagram_thread_points_to_start(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _guest, _inq, ig = _instagram_lead(db, tid)
    resp = client.post(f"/api/v1/conversations/{ig.id}/send-template",
                       json={"template_id": _template(db, tid).id, "variables": ["N"]}, headers=_h(tenant_and_user))
    assert resp.status_code == 422 and "Start on WhatsApp" in resp.json()["detail"]


# ── No-answer playbook (P2) for an Instagram-only guest ─────────────────────

def _enable_p2(db, tid):
    tenant = db.query(Tenant).filter_by(id=tid).first()
    pb_settings.update(db, tenant, None, {"playbooks": {cat.UNANSWERED_OUTBOUND: {"enabled": True}}})
    t = pack.BY_NAME[pack.TRIED_CALLING]
    db.add(WATemplate(tenant_id=tid, name=pack.TRIED_CALLING, language="en", category=TemplateCategory.UTILITY,
                      status=TemplateStatus.APPROVED, components=[dict(c) for c in t["components"]]))
    db.commit()


def _outbound(db, tid, guest, inq, *, dial="no-answer", at=None, ai=None):
    call = Call(id=str(uuid.uuid4()), tenant_id=tid, guest_id=guest.id, inquiry_id=inq.id, ivr_provider="vobiz",
                ivr_call_id=f"c-{uuid.uuid4().hex[:10]}", direction=CallDirection.OUTBOUND, from_number="+912271264296",
                to_number=guest.phone, duration_seconds=22, ivr_dial_status=dial, ai_disposition=ai,
                created_at=at or datetime.now(timezone.utc))
    db.add(call)
    db.commit()
    return call


def _no_sends():
    return patch("app.workers.tasks.send_whatsapp.send_whatsapp_template.delay")


def test_instagram_only_guest_with_phone_gets_the_no_answer_template(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _enable_p2(db, tid)
    guest, inq, _ig = _instagram_lead(db, tid)
    call = _outbound(db, tid, guest, inq)
    with _no_sends() as tpl:
        out = engine.on_call(db, tid, call.id)
    assert out["status"] == "done" and out.get("reason") is None
    tpl.assert_called_once()
    assert tpl.call_args.kwargs["template_name"] == pack.TRIED_CALLING
    wa = _wa_convs(db, tid, guest.id)
    assert len(wa) == 1 and not wa[0].is_personal_bridge       # sent from the official number, on a new WhatsApp thread


def test_late_ai_no_answer_still_sends_within_three_hours(db, tenant_and_user):
    """Vobiz said "completed" (a ringing tone / announcement); only the AI heard nobody, 50 min later."""
    tid = _tid(tenant_and_user)
    _enable_p2(db, tid)
    guest, inq, _ig = _instagram_lead(db, tid)
    call = _outbound(db, tid, guest, inq, dial="completed", ai="no_answer",
                     at=datetime.now(timezone.utc) - timedelta(minutes=50))
    with _no_sends() as tpl:
        assert engine.on_call(db, tid, call.id)["status"] == "too_old"          # the ingest-time limit still holds
        tpl.assert_not_called()
    db.query(PlaybookAction).filter_by(tenant_id=tid).delete()      # actions first: they reference the run (FK on PostgreSQL)
    db.query(PlaybookRun).filter_by(tenant_id=tid).delete()
    db.commit()
    with _no_sends() as tpl:
        out = engine.on_call(db, tid, call.id, classified_late=True)
    assert out["status"] == "done"
    tpl.assert_called_once()


def test_too_old_call_is_recorded_on_activity_not_dropped_silently(db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _enable_p2(db, tid)
    guest, inq, _ig = _instagram_lead(db, tid)
    call = _outbound(db, tid, guest, inq, at=datetime.now(timezone.utc) - timedelta(hours=5))
    with _no_sends() as tpl:
        out = engine.on_call(db, tid, call.id, classified_late=True)
    assert out["status"] == "too_old"
    tpl.assert_not_called()
    row = db.query(PlaybookAction).filter_by(tenant_id=tid, guest_id=guest.id).one()
    assert row.status == "skipped" and "too late" in row.reason


# ── Undeliverable receipts ──────────────────────────────────────────────────

def test_describe_turns_131026_into_plain_words():
    text = wa_delivery_errors.describe([{"code": 131026, "title": "Message undeliverable"}])
    assert text.startswith("This number isn't on WhatsApp") and "(Meta 131026)" in text
    assert "did not deliver" in wa_delivery_errors.describe([{"code": 1, "title": "x"}])


def test_undeliverable_template_shows_reason_and_lands_on_activity(client, db, tenant_and_user):
    from app.workers.tasks.whatsapp import _handle_status_update
    tid = _tid(tenant_and_user)
    guest, _inq, _ig = _instagram_lead(db, tid)
    resp, _ = _start(client, tenant_and_user, guest.id, _template(db, tid).id)
    msg = db.query(Message).filter_by(id=resp.json()["message"]["id"]).one()
    msg.channel_message_id = "wamid.TEST1"
    db.commit()
    tenant = db.query(Tenant).filter_by(id=tid).first()
    _handle_status_update(db, tenant, {"id": "wamid.TEST1", "status": "failed",
                                       "errors": [{"code": 131026, "title": "Message undeliverable"}]})
    db.commit()
    db.refresh(msg)
    assert msg.delivery_state == MessageDeliveryState.FAILED
    assert msg.delivery_error.startswith("This number isn't on WhatsApp")
    row = db.query(PlaybookAction).filter_by(tenant_id=tid, message_id=msg.id).one()
    assert row.playbook_key == wa_delivery_errors.MANUAL_TEMPLATE and row.status == "failed" and row.guest_id == guest.id
