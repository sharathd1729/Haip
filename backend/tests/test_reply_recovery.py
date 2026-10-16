"""A guest message that never got any reply (no AI draft, no human reply) is re-queued for the concierge, once, and nothing else is."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.usefixtures("capabilities_seeded")

from app.models.base import gen_uuid  # noqa: E402
from app.models.conversation import ChannelType, Conversation, Message  # noqa: E402
from app.models.guest import Guest  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.workers.tasks import reply_recovery as rr  # noqa: E402


def _ago(minutes):
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


def _conv(db, tid, channel=ChannelType.WHATSAPP, **kw):
    g = Guest(id=gen_uuid(), tenant_id=tid, name="G", phone=f"+9198{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    db.flush()
    c = Conversation(id=gen_uuid(), tenant_id=tid, guest_id=g.id, channel=channel, **kw)
    db.add(c)
    db.flush()
    return c


def _msg(db, tid, c, direction, minutes, body="Is it free this weekend?", **kw):
    m = Message(id=gen_uuid(), tenant_id=tid, conversation_id=c.id, direction=direction, channel="whatsapp", body=body, created_at=_ago(minutes), **kw)
    db.add(m)
    db.flush()
    return m


@pytest.fixture()
def run(db, monkeypatch):
    """Run the per-tenant task against the test session with the queue and cache faked."""
    sent, cache = MagicMock(), {}
    monkeypatch.setattr(rr, "SessionLocal", lambda: db)
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(rr, "get_cached", lambda k: cache.get(k))
    monkeypatch.setattr(rr, "set_cached", lambda k, v, ttl=0: cache.__setitem__(k, v))
    monkeypatch.setattr("app.workers.tasks.concierge_draft.concierge_draft.apply_async", sent)
    monkeypatch.setattr("app.services.concierge_service.mark_pending_draft", lambda *a, **k: None)
    return lambda tid: (rr.recover_missed_replies(tid), sent)


def test_an_unanswered_message_is_requeued_once(db, tenant_and_user, run):
    tid = tenant_and_user["tenant"].id
    c = _conv(db, tid)
    m = _msg(db, tid, c, "inbound", 12)
    db.commit()
    out, sent = run(tid)
    assert out["queued"] == 1
    assert sent.call_args.kwargs["kwargs"] == {"message_id": m.id, "conversation_id": c.id, "tenant_id": tid}
    out2, sent2 = run(tid)                                           # the hourly guard: not again
    assert out2["queued"] == 0 and out2["skipped"] == 1


@pytest.mark.parametrize("name,setup", [
    ("a draft exists (even a failed-provider holding reply)", lambda db, tid, c: _msg(db, tid, c, "outbound", 10, is_ai_generated=True)),
    ("a person replied", lambda db, tid, c: _msg(db, tid, c, "outbound", 9, is_ai_generated=False)),
])
def test_an_answered_message_is_left_alone(db, tenant_and_user, run, name, setup):
    tid = tenant_and_user["tenant"].id
    c = _conv(db, tid)
    _msg(db, tid, c, "inbound", 12)
    setup(db, tid, c)
    db.commit()
    assert run(tid)[0]["queued"] == 0


def test_an_internal_note_is_not_a_reply(db, tenant_and_user, run):
    tid = tenant_and_user["tenant"].id
    c = _conv(db, tid)
    _msg(db, tid, c, "inbound", 12)
    _msg(db, tid, c, "outbound", 10, body="call them", is_internal=True)
    db.commit()
    assert run(tid)[0]["queued"] == 1


@pytest.mark.parametrize("minutes,expected", [(2, 0), (5, 1), (60 * 5, 1), (60 * 7, 0)])
def test_only_messages_between_four_minutes_and_six_hours_old(db, tenant_and_user, run, minutes, expected):
    tid = tenant_and_user["tenant"].id
    c = _conv(db, tid)
    _msg(db, tid, c, "inbound", minutes)
    db.commit()
    assert run(tid)[0]["queued"] == expected


def test_no_text_closed_sample_and_off_threads_are_skipped(db, tenant_and_user, run):
    tid = tenant_and_user["tenant"].id
    _msg(db, tid, _conv(db, tid), "inbound", 12, body="")
    _msg(db, tid, _conv(db, tid), "inbound", 12, body="[image]")
    _msg(db, tid, _conv(db, tid, is_open=False), "inbound", 12)
    _msg(db, tid, _conv(db, tid, is_sample=True), "inbound", 12)
    _msg(db, tid, _conv(db, tid, ai_mode="off"), "inbound", 12)
    db.commit()
    assert run(tid)[0]["queued"] == 0


def test_only_the_latest_guest_message_of_a_thread_is_queued(db, tenant_and_user, run):
    tid = tenant_and_user["tenant"].id
    c = _conv(db, tid)
    _msg(db, tid, c, "inbound", 30, body="Hi")
    latest = _msg(db, tid, c, "inbound", 12, body="Any caravan free?")
    db.commit()
    out, sent = run(tid)
    assert out["queued"] == 1 and sent.call_args.kwargs["kwargs"]["message_id"] == latest.id


def test_another_workspaces_messages_are_never_queued(db, tenant_and_user, run):
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    _msg(db, other.id, _conv(db, other.id), "inbound", 12)
    db.commit()
    assert run(tenant_and_user["tenant"].id)[0]["queued"] == 0
