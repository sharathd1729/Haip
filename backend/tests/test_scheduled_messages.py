"""Scheduled inbox messages (tasks scheduled_messages.send_due): a due one goes to the channel's sender exactly once; a
future one, an internal note or another workspace's is left alone; a personal-bridge thread is refused in words."""
import uuid
from datetime import UTC, datetime, timedelta

from app.models.conversation import ChannelType, Conversation, Message, MessageDeliveryState
from app.models.guest import Guest
from app.models.tenant import Tenant
from app.workers.tasks import scheduled_messages as sm

NOW = datetime(2026, 11, 14, 9, 0, tzinfo=UTC)


def _world(db, source=None):
    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"sm-{uuid.uuid4().hex[:8]}", plan="growth")
    db.add(t)
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="G", phone="+919999012345")
    db.add(g)
    db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel=ChannelType.WHATSAPP, is_open=True,
                     source=source)
    db.add(c)
    db.commit()
    return t, c


def _msg(db, t, c, when, **kw):
    m = Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=c.id, direction="outbound", channel="whatsapp",
                body="Reminder", scheduled_for=when, **kw)
    db.add(m)
    db.commit()
    return m


def test_due_messages_are_sent_once_and_the_rest_wait(db):
    t, c = _world(db)
    due = _msg(db, t, c, "2026-11-14T08:59:00Z")
    naive_due = _msg(db, t, c, "2026-11-14T08:00:00")           # no zone = UTC
    later = _msg(db, t, c, "2026-11-14T10:00:00+05:30")         # 04:30 UTC... is due too
    future = _msg(db, t, c, "2026-11-15T09:00:00Z")
    note = _msg(db, t, c, "2026-11-14T08:00:00Z", is_internal=True)
    other_t, other_c = _world(db)
    theirs = _msg(db, other_t, other_c, "2026-11-14T08:00:00Z")
    sent = []
    out = sm.send_due(db, t.id, NOW, dispatch=lambda ch, mid, tid: sent.append((ch, mid, tid)))
    assert out == {"sent": 3, "failed": 0}
    assert {m for _, m, _ in sent} == {due.id, naive_due.id, later.id} and all(x[0] == "whatsapp" for x in sent)
    db.expire_all()
    assert db.get(Message, due.id).delivery_state == MessageDeliveryState.QUEUED
    assert db.get(Message, future.id).delivery_state is None and db.get(Message, note.id).delivery_state is None
    assert db.get(Message, theirs.id).delivery_state is None
    assert sm.send_due(db, t.id, NOW, dispatch=lambda *a: sent.append(a)) == {"sent": 0, "failed": 0}   # never twice


def test_personal_bridge_and_stale_messages_fail_in_words(db):
    t, bridge = _world(db, source="personal_bridge")
    m = _msg(db, t, bridge, "2026-11-14T08:00:00Z")
    _, c = t, _world(db)[1]
    old = _msg(db, db.get(Tenant, c.tenant_id), c, "2026-11-01T08:00:00Z")
    assert sm.send_due(db, t.id, NOW, dispatch=lambda *a: None) == {"sent": 0, "failed": 1}
    assert sm.send_due(db, c.tenant_id, NOW, dispatch=lambda *a: None) == {"sent": 0, "failed": 1}
    db.expire_all()
    assert "read-only" in db.get(Message, m.id).delivery_error and "week" in db.get(Message, old.id).delivery_error


def test_broker_down_puts_the_message_back(db):
    t, c = _world(db)
    m = _msg(db, t, c, "2026-11-14T08:00:00Z")

    def down(*a):
        raise ConnectionError("broker down")

    assert sm.send_due(db, t.id, NOW, dispatch=down) == {"sent": 0, "failed": 0}
    db.expire_all()
    assert db.get(Message, m.id).delivery_state is None
    assert sm.send_due(db, t.id, NOW + timedelta(minutes=1), dispatch=lambda *a: None)["sent"] == 1
