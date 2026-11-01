"""AI drafts nobody acted on are closed as "expired" (services/ai_draft_expiry.py): (a) superseded, (b) a later send, (c) 24 h old."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.ai_draft_outcome import AIDraftOutcome
from app.models.audit_event import AuditEvent
from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.services import ai_draft_expiry

pytestmark = pytest.mark.usefixtures("capabilities_seeded")   # approve/reject are gated by conversations.send

NOW = datetime.now(timezone.utc)


def _tid(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _conv(db, tenant_id):
    guest = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, phone=f"+9198{uuid.uuid4().int % 10**8:08d}", name="Expiry Guest")
    db.add(guest); db.flush()
    conv = Conversation(id=str(uuid.uuid4()), tenant_id=tenant_id, guest_id=guest.id, channel=ChannelType.WHATSAPP, is_open=True)
    db.add(conv); db.commit()
    return conv


def _draft(db, conv, age=timedelta(minutes=5)):
    m = Message(id=str(uuid.uuid4()), tenant_id=conv.tenant_id, conversation_id=conv.id, direction="outbound", channel="whatsapp",
                body="Thanks for your message! Let me check and get right back to you.", is_ai_generated=True, was_approved=None,
                created_at=NOW - age)
    db.add(m); db.commit()
    return m


def _sent(db, conv, age=timedelta(minutes=1), sender_kind="human"):
    m = Message(id=str(uuid.uuid4()), tenant_id=conv.tenant_id, conversation_id=conv.id, direction="outbound", channel="whatsapp",
                body="Hi, the caravan is free that weekend.", sender_kind=sender_kind, delivery_state=MessageDeliveryState.SENT,
                channel_message_id=f"wamid-{uuid.uuid4().hex[:8]}", created_at=NOW - age)
    db.add(m); db.commit()
    return m


def _outcomes(db, msg):
    return [o.outcome for o in db.query(AIDraftOutcome).filter_by(draft_message_id=msg.id).all()]


def _audits(db, tenant_id, conversation_id=None):
    q = db.query(AuditEvent).filter_by(tenant_id=tenant_id, action="ai_draft.expired")
    return q.filter_by(target_id=conversation_id).all() if conversation_id else q.all()


def test_rule_a_superseded_draft_is_expired_not_rejected(db, tenant_and_user):
    conv = _conv(db, _tid(tenant_and_user))
    d = _draft(db, conv)
    assert ai_draft_expiry.expire(db, conv.tenant_id, conv.id, [d.id], "superseded") == [d.id]
    db.commit(); db.refresh(d)
    assert d.was_approved is False and d.channel_status == "expired" and ai_draft_expiry.is_expired(d)
    assert d.body.startswith("Thanks for your message")          # kept, never deleted
    assert _outcomes(db, d) == ["expired"]
    audit = _audits(db, conv.tenant_id, conv.id)
    assert len(audit) == 1 and audit[0].payload["reason"] == "superseded" and audit[0].actor_user_id is None


def test_rule_b_a_later_send_expires_older_drafts_only(db, tenant_and_user):
    conv = _conv(db, _tid(tenant_and_user))
    older1, older2 = _draft(db, conv, age=timedelta(minutes=10)), _draft(db, conv, age=timedelta(minutes=9))
    newer = _draft(db, conv, age=timedelta(seconds=10))           # written after the sent message: answers something newer
    sent = _sent(db, conv, age=timedelta(minutes=1))
    assert sorted(ai_draft_expiry.after_send(db, sent)) == sorted([older1.id, older2.id])
    for m in (older1, older2, newer):
        db.refresh(m)
    assert ai_draft_expiry.is_expired(older1) and ai_draft_expiry.is_expired(older2) and newer.was_approved is None
    assert len(_audits(db, conv.tenant_id, conv.id)) == 1         # ONE audit row for the conversation's batch


def test_rule_b_skips_the_consult_holding_reply(db, tenant_and_user):
    conv = _conv(db, _tid(tenant_and_user))
    held = _draft(db, conv, age=timedelta(minutes=2))
    holding = _sent(db, conv, age=timedelta(minutes=1), sender_kind="ai_holding")
    assert ai_draft_expiry.after_send(db, holding) == []
    assert ai_draft_expiry.sweep(db, conv.tenant_id, now=NOW) == 0
    db.refresh(held)
    assert held.was_approved is None


def test_rule_c_sweep_expires_old_and_backstops_b_and_is_idempotent(db, tenant_and_user):
    conv = _conv(db, _tid(tenant_and_user))
    old = _draft(db, conv, age=timedelta(hours=25))
    fresh = _draft(db, conv, age=timedelta(hours=2))
    conv2 = _conv(db, conv.tenant_id)
    missed = _draft(db, conv2, age=timedelta(hours=2))
    _sent(db, conv2, age=timedelta(hours=1))                      # a send the inline hook did not see
    approved = _draft(db, conv, age=timedelta(hours=30))
    approved.was_approved = True; db.commit()

    assert ai_draft_expiry.sweep(db, conv.tenant_id, now=NOW) == 2
    db.commit()
    assert ai_draft_expiry.sweep(db, conv.tenant_id, now=NOW) == 0       # idempotent
    db.commit()
    for m in (old, fresh, missed, approved):
        db.refresh(m)
    assert ai_draft_expiry.is_expired(old) and ai_draft_expiry.is_expired(missed)
    assert fresh.was_approved is None and approved.was_approved is True
    assert _outcomes(db, old) == ["expired"] and _outcomes(db, missed) == ["expired"] and _outcomes(db, approved) == []
    assert {e.payload["reason"] for e in _audits(db, conv.tenant_id)} == {"older_than_24h", "later_message_sent"}


def test_sweep_and_expire_are_tenant_isolated(db, tenant_and_user):
    conv = _conv(db, _tid(tenant_and_user))
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other); db.commit()
    other_conv = _conv(db, other.id)
    mine, theirs = _draft(db, conv, age=timedelta(hours=30)), _draft(db, other_conv, age=timedelta(hours=30))
    assert ai_draft_expiry.sweep(db, conv.tenant_id, now=NOW) == 1
    db.commit()
    assert ai_draft_expiry.expire(db, conv.tenant_id, other_conv.id, [theirs.id], "superseded") == []   # wrong tenant: nothing
    db.refresh(mine); db.refresh(theirs)
    assert ai_draft_expiry.is_expired(mine) and theirs.was_approved is None
    assert _audits(db, other.id) == []


def test_expired_draft_cannot_be_approved_or_rejected(client, db, tenant_and_user):
    headers = {"Authorization": f"Bearer {tenant_and_user['access_token']}"}
    conv = _conv(db, _tid(tenant_and_user))
    d = _draft(db, conv)
    ai_draft_expiry.expire(db, conv.tenant_id, conv.id, [d.id], "superseded"); db.commit()
    for action in ("approve", "reject"):
        r = client.post(f"/api/v1/conversations/{conv.id}/messages/{d.id}/{action}", json={}, headers=headers)
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == "draft_expired"
    shown = next(m for m in client.get(f"/api/v1/conversations/{conv.id}", headers=headers).json()["messages"] if m["id"] == d.id)
    assert shown["draft_expired"] is True and shown["text"]           # flagged, text still readable
    assert _outcomes(db, d) == ["expired"]                            # no approve/reject outcome written


def test_leads_pending_draft_ignores_expired(db, tenant_and_user):
    from app.models.inquiry import Inquiry
    from app.services.leads_service import _batch_pending_drafts
    tid = _tid(tenant_and_user)
    conv = _conv(db, tid)
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=tid, guest_id=conv.guest_id)
    db.add(inq); db.flush()
    conv.inquiry_id = inq.id; db.commit()
    d = _draft(db, conv)
    assert inq.id in _batch_pending_drafts(db, tid, [inq.id])
    ai_draft_expiry.expire(db, tid, conv.id, [d.id], "superseded"); db.commit()
    assert inq.id not in _batch_pending_drafts(db, tid, [inq.id])
