"""Follow-up messages after an automation's final message (services/ig_sequence.py, Automations v2 phase 3).

Up to 3 steps with waits; they start only where the chat is open; each step stops if the guest or anyone else wrote,
a DM form is running, or the window has closed; workspaces never mix.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.models.automation import AutomationRule
from app.models.conversation import ChannelType, Conversation, Message, MessageDirection
from app.models.guest import Guest
from app.models.ig_automation import IgAutomationEvent, IgFormSession, IgTrackedLink
from app.models.tenant import Tenant
from app.schemas.ig_automation import validate_ig_rule
from app.services import ig_automation, ig_sequence

SEQ = [
    {"text": "Did you see the villas, {first_name}?", "after_minutes": 60},
    {"text": "Weekend dates are filling up.", "after_minutes": 180,
     "button": {"title": "Check dates", "url": "https://x.in/d"}},
]


class FakeIG:
    def __init__(self):
        self.calls = []

    def _ok(self, *call):
        self.calls.append(call)
        return {"message_id": f"mid.{len(self.calls)}"}

    def send_text(self, rid, text): return self._ok("text", rid, text)
    def send_quick_replies(self, rid, text, quick): return self._ok("quick", rid, text)
    def send_private_reply(self, comment_id, text, quick=None): return self._ok("private", comment_id, text, quick)
    def send_link_button(self, rid, text, title, url): return self._ok("button", rid, text, title, url)
    def reply_to_comment(self, comment_id, text): return self._ok("public", comment_id, text)
    def follows_us(self, rid): return None


@pytest.fixture
def ig(monkeypatch):
    fake = FakeIG()
    monkeypatch.setattr(ig_automation, "_adapter", lambda db, tenant_id: fake)
    return fake


@pytest.fixture
def queued(monkeypatch):
    out = []
    monkeypatch.setattr(ig_sequence, "_queue", lambda *a: out.append(a))
    return out


def _world(db, trigger="ig_dm_received", ac=None):
    t = Tenant(id=str(uuid.uuid4()), name="Neelgiri", slug=f"n-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Ananya Rao")
    c = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel=ChannelType.INSTAGRAM)
    r = AutomationRule(id=str(uuid.uuid4()), tenant_id=t.id, name="PRICE", trigger=trigger,
                       trigger_config={"keywords": ["price"]}, action="send_instagram_quick_reply",
                       action_config={"message": "Here are our prices.", "sequence": SEQ, **(ac or {})},
                       is_active=True, run_count=0)
    db.add_all([g, c, r])
    db.commit()
    return t, g, c, r


def _msg(db, t, c, direction, minutes_ago, kind=None):
    db.add(Message(id=str(uuid.uuid4()), tenant_id=t.id, conversation_id=c.id, direction=direction,
                   channel=ChannelType.INSTAGRAM, body="hi", sender_kind=kind,
                   created_at=datetime.now(UTC) - timedelta(minutes=minutes_ago)))
    db.commit()


def _step(db, t, g, c, r, step=0, started_minutes_ago=61):
    started = (datetime.now(UTC) - timedelta(minutes=started_minutes_ago)).isoformat()
    return ig_sequence.send_step(db, t.id, r.id, g.id, c.id, "igsid", step, started)


def _stopped(db, r):
    return [e.detail for e in db.query(IgAutomationEvent).filter_by(rule_id=r.id, kind="sequence_stopped")]


def test_the_sequence_is_validated():
    ok = validate_ig_rule("ig_dm_received", {"keywords": ["price"]}, {"message": "x", "sequence": SEQ})[1]
    assert len(ok["sequence"]) == 2
    too_long = [{"text": "a", "after_minutes": 1000}, {"text": "b", "after_minutes": 400}]
    with pytest.raises(ValidationError):  # all of it must fit in Instagram's window
        validate_ig_rule("ig_dm_received", {"keywords": ["price"]}, {"message": "x", "sequence": too_long})
    with pytest.raises(ValidationError):
        validate_ig_rule("ig_dm_received", {"keywords": ["price"]},
                         {"message": "x", "sequence": [{"text": "a", "after_minutes": 10}] * 4})


def test_an_open_chat_starts_the_follow_ups_after_the_final_message(db, ig, queued):
    t, g, c, r = _world(db)
    assert ig_automation.start(db, t.id, r, recipient_id="igsid", guest_id=g.id, conversation_id=c.id, guest=g)
    assert len(queued) == 1 and queued[0][5] == 0 and queued[0][7] == 60


def test_a_comments_private_reply_alone_never_starts_them(db, ig, queued, monkeypatch):
    from app.core import cache
    monkeypatch.setattr(cache, "idem_check_and_set", lambda key, ttl=0: True)
    t, g, c, r = _world(db, trigger="ig_comment_received")
    ig_automation.start(db, t.id, r, recipient_id="igsid", guest_id=g.id, conversation_id=c.id, comment_id="cm1", guest=g)
    assert queued == []


def test_after_the_tap_the_final_message_starts_them(db, ig, queued):
    t, g, c, r = _world(db, trigger="ig_comment_received", ac={"button": {"title": "See", "url": "https://x.in"}})
    ig_automation.handle_payload(db, t.id, f"igauto:{r.id}:open", recipient_id="igsid", guest_id=g.id,
                                 conversation_id=c.id, guest=g)
    assert ig.calls[-1][0] == "button" and len(queued) == 1


def test_a_step_is_sent_and_the_next_one_queued(db, ig, queued):
    t, g, c, r = _world(db)
    _msg(db, t, c, MessageDirection.INBOUND, 70)  # their keyword, before the sequence started
    assert _step(db, t, g, c, r, 0) == "sent"
    assert ig.calls[-1] == ("text", "igsid", "Did you see the villas, Ananya?")
    assert len(queued) == 1 and queued[0][5] == 1 and queued[0][7] == 180
    assert _step(db, t, g, c, r, 1) == "sent"  # its own earlier follow-up doesn't stop it
    name, _, _, title, _url = ig.calls[-1]
    assert name == "button" and title == "Check dates"
    assert db.query(IgTrackedLink).filter_by(rule_id=r.id).count() == 1


@pytest.mark.parametrize("direction,reason", [
    (MessageDirection.INBOUND, "guest_replied"),
    (MessageDirection.OUTBOUND, "someone_answered"),
])
def test_anyone_writing_stops_the_sequence(db, ig, queued, direction, reason):
    t, g, c, r = _world(db)
    _msg(db, t, c, direction, 10)
    assert _step(db, t, g, c, r) == f"stopped: {reason}"
    assert ig.calls == [] and queued == [] and _stopped(db, r) == [f"step 1: {reason}"]


def test_a_closed_window_or_a_running_form_stops_it(db, ig, queued):
    t, g, c, r = _world(db)
    _msg(db, t, c, MessageDirection.INBOUND, 24 * 60)  # their last message was a day ago
    assert _step(db, t, g, c, r, started_minutes_ago=23 * 60 + 30) == "stopped: window_closed"

    t2, g2, c2, r2 = _world(db)
    _msg(db, t2, c2, MessageDirection.INBOUND, 70)
    db.add(IgFormSession(tenant_id=t2.id, rule_id=r2.id, guest_id=g2.id, conversation_id=c2.id, recipient_id="igsid",
                         step=0, answers={}, status="active", expires_at=datetime.now(UTC) + timedelta(hours=5)))
    db.commit()
    assert _step(db, t2, g2, c2, r2) == "stopped: form_running"
    assert ig.calls == []


def test_steps_never_cross_workspaces(db, ig, queued):
    t, g, c, r = _world(db)
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    started = datetime.now(UTC).isoformat()
    assert ig_sequence.send_step(db, other.id, r.id, g.id, c.id, "igsid", 0, started) == "skipped: no such step"
    assert ig.calls == []
