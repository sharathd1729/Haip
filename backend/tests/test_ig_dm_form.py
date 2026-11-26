"""Instagram DM forms (services/ig_dm_form.py, Automations v2 phase 1).

After the tap, HAIP asks the rule's questions one at a time; the WhatsApp number makes the person a lead through the
normal phone path; the answers land on the enquiry; then the rule's message goes out. Typed answers, a bad number,
a returning guest, "talk to a person", "stop", questions mid-form, the reminder and workspace separation are covered.
"""

import uuid

import pytest
from pydantic import ValidationError

from app.models.automation import AutomationRule
from app.models.conversation import ChannelType, Conversation
from app.models.guest import Guest
from app.models.ig_automation import IgAutomationEvent, IgFormSession
from app.models.inquiry import Inquiry
from app.models.tenant import Tenant
from app.schemas.ig_automation import validate_ig_rule
from app.services import chat_phone_capture, ig_automation, ig_dm_form

PHONE = "+91 98861 40372"
FORM = {
    "enabled": True,
    "questions": [
        {"key": "dates", "text": "When are you planning to come?", "options": ["This weekend", "Next month"]},
        {"key": "guests", "text": "How many guests?", "options": ["2", "4", "6", "8+"]},
        {"key": "phone", "text": "Your WhatsApp number, so our team can send the quote."},
    ],
}


class FakeIG:
    def __init__(self):
        self.calls = []

    def _ok(self, *call):
        self.calls.append(call)
        return {"message_id": f"mid.{len(self.calls)}"}

    def send_text(self, rid, text): return self._ok("text", rid, text)
    def send_quick_replies(self, rid, text, quick): return self._ok("quick", rid, text, [q["title"] for q in quick])
    def send_private_reply(self, comment_id, text, quick=None): return self._ok("private", comment_id, text, quick)
    def send_link_button(self, rid, text, title, url): return self._ok("button", rid, text, title, url)
    def reply_to_comment(self, comment_id, text): return self._ok("public", comment_id, text)
    def follows_us(self, rid): return None

    def last_text(self): return self.calls[-1][2]


@pytest.fixture
def ig(monkeypatch):
    fake = FakeIG()
    monkeypatch.setattr(ig_automation, "_adapter", lambda db, tenant_id: fake)
    monkeypatch.setattr(ig_dm_form, "_schedule_reminder", lambda session: None)
    monkeypatch.setattr(ig_dm_form, "_refresh_summary", lambda tenant_id, inquiry_id: None)
    return fake


def _world(db, form=None, trigger="ig_comment_received", ac=None):
    t = Tenant(id=str(uuid.uuid4()), name="Neelgiri", slug=f"n-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    g = Guest(id=str(uuid.uuid4()), tenant_id=t.id, name="Ananya Rao")
    db.add(g)
    db.flush()
    inq = Inquiry(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id)
    db.add(inq)
    db.flush()
    c = Conversation(id=str(uuid.uuid4()), tenant_id=t.id, guest_id=g.id, channel=ChannelType.INSTAGRAM, inquiry_id=inq.id)
    r = AutomationRule(id=str(uuid.uuid4()), tenant_id=t.id, name="PRICE reel", trigger=trigger,
                       trigger_config={"keywords": ["price"]}, action="send_instagram_quick_reply",
                       action_config={"message": "Thanks {first_name}! {agent_name} will WhatsApp you soon.",
                                      "form": form if form is not None else FORM, **(ac or {})},
                       is_active=True, run_count=0)
    db.add_all([c, r])
    db.commit()
    return t, g, c, inq, r


def _tap(db, t, g, c, r):
    return ig_automation.handle_payload(db, t.id, f"igauto:{r.id}:open", recipient_id="igsid", guest_id=g.id,
                                        conversation_id=c.id, guest=g)


def _say(db, t, g, text):
    # what process_instagram_dm does before handing a message to the form: capture any phone in it
    chat_phone_capture.capture_from_text(db, t.id, g.id, text, source="message_text")
    used = ig_dm_form.handle_inbound(db, t.id, g.id, text, guest=g)
    db.commit()
    return used


def _kinds(db, r):
    return [e.kind for e in db.query(IgAutomationEvent).filter_by(rule_id=r.id).order_by(IgAutomationEvent.created_at)]


def test_the_tap_starts_the_questions_and_the_answers_make_a_lead(db, ig):
    t, g, c, inq, r = _world(db)
    assert _tap(db, t, g, c, r)
    assert ig.calls[-1] == ("quick", "igsid", "When are you planning to come?", ["This weekend", "Next month"])

    assert _say(db, t, g, "12 to 14 Dec")
    assert ig.calls[-1][2] == "How many guests?"
    assert _say(db, t, g, "we are 6")
    assert "WhatsApp number" in ig.last_text()
    assert _say(db, t, g, PHONE)

    assert chat_phone_capture.guest_has_phone(db, t.id, g.id)          # a lead through the normal phone path
    assert ig.last_text() == "Thanks Ananya! our team will WhatsApp you soon."
    db.refresh(inq)
    assert inq.adults == 6 and "Dates: 12 to 14 Dec" in inq.special_requests and "Guests: we are 6" in inq.special_requests
    assert PHONE not in (inq.special_requests or "")                    # the number lives on the guest, not in notes
    session = db.query(IgFormSession).filter_by(guest_id=g.id).one()
    assert session.status == "completed" and session.answers["phone"] == "shared"
    assert {"form_started", "form_completed"} <= set(_kinds(db, r))
    # a second tap after finishing sends nothing
    n = len(ig.calls)
    _tap(db, t, g, c, r)
    assert len(ig.calls) == n


def test_a_bad_number_is_asked_again_once_then_the_team_takes_over(db, ig):
    t, g, c, inq, r = _world(db, form={"enabled": True, "questions": [{"key": "phone", "text": "Your WhatsApp number?"}]})
    _tap(db, t, g, c, r)
    assert _say(db, t, g, "my number is 123")
    assert "doesn't look right" in ig.last_text()
    assert _say(db, t, g, "not sharing")
    assert "team will reply" in ig.last_text()
    assert db.query(IgFormSession).filter_by(guest_id=g.id).one().status == "handed_over"
    assert _say(db, t, g, "hello?") is False                            # the form is over: the inbox/AI has the chat


def test_a_returning_guest_with_a_number_is_not_asked_for_it(db, ig):
    t, g, c, inq, r = _world(db, form={"enabled": True, "questions": [
        {"key": "guests", "text": "How many guests?"}, {"key": "phone", "text": "Your WhatsApp number?"}]})
    chat_phone_capture.capture_from_text(db, t.id, g.id, PHONE)
    db.commit()
    _tap(db, t, g, c, r)
    assert _say(db, t, g, "4")
    assert "Your WhatsApp number?" not in [call[2] for call in ig.calls]
    assert db.query(IgFormSession).filter_by(guest_id=g.id).one().status == "completed"


def test_talk_to_a_person_and_stop_end_the_form(db, ig):
    t, g, c, inq, r = _world(db)
    _tap(db, t, g, c, r)
    assert _say(db, t, g, "Can I talk to a person")
    assert db.query(IgFormSession).filter_by(guest_id=g.id).one().status == "handed_over"

    t2, g2, c2, _, r2 = _world(db)
    _tap(db, t2, g2, c2, r2)
    assert _say(db, t2, g2, "stop")
    assert db.query(IgFormSession).filter_by(guest_id=g2.id).one().status == "stopped"
    assert "stopped" in ig.last_text()                                   # one confirmation, nothing after it


def test_a_question_mid_form_goes_to_the_ai_and_the_form_waits(db, ig):
    t, g, c, inq, r = _world(db)
    _tap(db, t, g, c, r)
    assert _say(db, t, g, "Is breakfast included?") is False
    assert db.query(IgFormSession).filter_by(guest_id=g.id).one().step == 0
    assert _say(db, t, g, "Next month")
    assert ig.last_text() == "How many guests?"


def test_a_dm_keyword_starts_the_questions_without_a_tap(db, ig):
    t, g, c, inq, r = _world(db, trigger="ig_dm_received")
    assert ig_automation.start(db, t.id, r, recipient_id="igsid", guest_id=g.id, conversation_id=c.id, guest=g)
    assert ig.calls[-1][2] == "When are you planning to come?"
    assert "dm_sent" in _kinds(db, r) and "form_started" in _kinds(db, r)


def test_a_comment_gets_the_opener_with_a_button_first(db, ig, monkeypatch):
    from app.core import cache
    monkeypatch.setattr(cache, "idem_check_and_set", lambda key, ttl=0: True)
    t, g, c, inq, r = _world(db)
    ig_automation.start(db, t.id, r, recipient_id="igsid", guest_id=g.id, conversation_id=c.id, comment_id="cm1", guest=g)
    name, _, text, quick = ig.calls[-1]
    assert name == "private" and quick and quick[0]["payload"] == f"igauto:{r.id}:open"
    assert db.query(IgFormSession).filter_by(guest_id=g.id).count() == 0   # the questions wait for the tap


def test_the_reminder_is_sent_once_and_only_on_the_same_question(db, ig):
    t, g, c, inq, r = _world(db)
    _tap(db, t, g, c, r)
    s = db.query(IgFormSession).filter_by(guest_id=g.id).one()
    assert ig_dm_form.remind(db, t.id, s.id, 0) == "sent" and ig.last_text().startswith("Just checking in")
    assert ig_dm_form.remind(db, t.id, s.id, 0) == "skipped"
    _say(db, t, g, "Next month")
    assert ig_dm_form.remind(db, t.id, s.id, 0) == "skipped"             # they already answered that one


def test_sessions_never_cross_workspaces(db, ig):
    t, g, c, inq, r = _world(db)
    _tap(db, t, g, c, r)
    other = Tenant(id=str(uuid.uuid4()), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(other)
    db.commit()
    assert ig_dm_form.active_session(db, other.id, g.id) is None
    assert ig_dm_form.handle_inbound(db, other.id, g.id, "Next month") is False
    s = db.query(IgFormSession).filter_by(guest_id=g.id).one()
    assert ig_dm_form.remind(db, other.id, s.id, 0) == "skipped"


def test_the_form_config_is_validated():
    ok = {"message": "Thanks!", "form": FORM}
    assert validate_ig_rule("ig_comment_received", {"keywords": ["price"]}, ok)[1]["form"]["enabled"] is True
    no_phone = {"message": "x", "form": {"enabled": True, "questions": [{"key": "email", "text": "Email?"}]}}
    assert validate_ig_rule("ig_comment_received", {"keywords": ["price"]}, no_phone)  # email only: details, not a lead
    two_phones = {"message": "x", "form": {"enabled": True, "questions": [
        {"key": "phone", "text": "Number?"}, {"key": "phone", "text": "Again?"}]}}
    with pytest.raises(ValidationError):
        validate_ig_rule("ig_comment_received", {"keywords": ["price"]}, two_phones)
    long_option = {"message": "x", "form": {"enabled": True, "questions": [
        {"key": "phone", "text": "Number?"}, {"key": "dates", "text": "When?", "options": ["Sometime in the next month"]}]}}
    with pytest.raises(ValidationError):
        validate_ig_rule("ig_comment_received", {"keywords": ["price"]}, long_option)
    off = {"message": "x", "form": {"enabled": False, "questions": []}}
    assert validate_ig_rule("ig_comment_received", {"keywords": ["price"]}, off)[1]["form"]["enabled"] is False


def test_dm_task_gives_a_form_answer_to_the_form_not_rules_or_the_ai(db, monkeypatch):
    from sqlalchemy.orm import Session as SASession

    from app.core.encryption import encrypt_credentials
    from app.models.integration import Integration
    from app.workers.tasks import process_instagram_dm as task

    t = Tenant(id=str(uuid.uuid4()), name="T", slug=f"t-{uuid.uuid4().hex[:6]}", plan="growth")
    db.add(t)
    db.flush()
    db.add(Integration(tenant_id=t.id, kind="instagram", status="active", config={"instagram_business_account_id": "1784"},
                       credentials_kms_blob=encrypt_credentials({"access_token": "tok"})))
    db.commit()
    seen = []
    monkeypatch.setattr(task, "SessionLocal", lambda: SASession(bind=db.connection()))
    monkeypatch.setattr(ig_dm_form, "handle_inbound", lambda db, tenant_id, guest_id, text, guest=None: seen.append(text) or True)
    monkeypatch.setattr("app.services.ig_keyword_match.find_matching_rule",
                        lambda *a, **k: pytest.fail("a form answer must not be keyword-matched"))
    monkeypatch.setattr("app.workers.tasks.concierge_draft.concierge_draft.apply_async",
                        lambda *a, **k: pytest.fail("the AI must stay out while a form runs"))
    out = task.process_instagram_dm.run({"ig_account_id": "1784", "sender_id": "igsid", "message_id": "mid.ans",
                                         "text": "Next month"})
    assert seen == ["Next month"] and out["status"] == "ok"
