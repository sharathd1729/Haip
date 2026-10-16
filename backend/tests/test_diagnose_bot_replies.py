"""scripts/diagnose_bot_replies.py is read-only and tells the owner why a guest got no reply."""
import importlib.util
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.models.base import gen_uuid
from app.models.conversation import ChannelType, Conversation, Message
from app.models.guest import Guest
from app.models.tenant import Tenant

pytestmark = pytest.mark.usefixtures("capabilities_seeded")

_SPEC = importlib.util.spec_from_file_location("diagnose_bot_replies", os.path.join(os.path.dirname(__file__), "..", "scripts", "diagnose_bot_replies.py"))
dbr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dbr)


def _now(minutes=0):
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


def _conv(db, tid, name):
    g = Guest(id=gen_uuid(), tenant_id=tid, name=name, phone=f"+9198{uuid.uuid4().int % 10**8:08d}")
    db.add(g)
    db.flush()
    c = Conversation(id=gen_uuid(), tenant_id=tid, guest_id=g.id, channel=ChannelType.WHATSAPP)
    db.add(c)
    db.flush()
    return c


def _msg(db, tid, c, direction, body, minutes, **kw):
    m = Message(id=gen_uuid(), tenant_id=tid, conversation_id=c.id, direction=direction, channel="whatsapp", body=body, created_at=_now(minutes), **kw)
    db.add(m)
    return m


def test_it_names_the_guests_still_waiting_and_why_and_changes_nothing(db, tenant_and_user, monkeypatch, capsys):
    tid = tenant_and_user["tenant"].id
    slug = db.query(Tenant).filter_by(id=tid).one().slug
    waiting = _conv(db, tid, "Waiting")
    _msg(db, tid, waiting, "inbound", "Is it free next weekend?", 300)
    _msg(db, tid, waiting, "outbound", "Thanks for your message! Let me check and get right back to you.", 299, is_ai_generated=True, was_approved=None,
         ai_needs_human_reason="AI reply generation failed after 2 attempts (RuntimeError: billing)")
    answered = _conv(db, tid, "Answered")
    _msg(db, tid, answered, "inbound", "Hi", 200)
    _msg(db, tid, answered, "outbound", "Hello!", 199, is_ai_generated=True, sent_autonomously=True, was_approved=True)
    failed = _conv(db, tid, "Failed")
    _msg(db, tid, failed, "inbound", "Hello?", 100)
    _msg(db, tid, failed, "outbound", "Hi there", 99, is_ai_generated=True, sent_autonomously=True, was_approved=True,
         delivery_state="failed", delivery_error="Error validating access token: Session has expired")
    db.commit()
    before = db.query(Message).count()

    spy = MagicMock(wraps=db)
    spy.commit, spy.rollback, spy.close = MagicMock(), MagicMock(), MagicMock()
    monkeypatch.setattr(dbr, "SessionLocal", lambda: spy)
    monkeypatch.setattr("sys.argv", ["diagnose_bot_replies.py", "--tenant-slug", slug, "--days", "3"])
    assert dbr.main() == 0
    out = capsys.readouterr().out
    assert "Guests still waiting for a reply: 2" in out                      # "Waiting" and "Failed" (its reply never delivered)
    assert "whatsapp   mode=shadow  confidence floor=0.78" in out                  # the real wa_/ig_ columns, not "default"
    assert "AI reply generation failed" in out and "access token expired" in out
    assert "generic holding reply  : 1" in out and "waiting for review     : 1" in out
    assert not spy.commit.called and spy.rollback.called and db.query(Message).count() == before    # read-only


def test_reason_and_error_grouping():
    assert dbr.reason_group("price leak: '₹5,000'; escalation: refund (matched 'refund')") == ["price leak", "escalation"]
    assert dbr.reason_group("AI reply generation failed after 2 attempts (RuntimeError: x)") == ["AI reply generation failed after 2 attempts"]
    assert dbr.error_group("Message failed: outside the allowed window (24 hours)") == "outside the 24-hour window"
    assert dbr.error_group("Session has expired") == "access token expired"
