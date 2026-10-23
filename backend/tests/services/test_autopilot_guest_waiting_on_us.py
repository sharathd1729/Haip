"""Lead autopilot rule 6 ("we spoke last, then silence" -> Lost) counts only OUR contact by the one contact rule: a person's
message or our call. The AI's own replies and holding lines, playbook/system messages and campaign broadcasts (old rows too)
never make a guest who is waiting on us look silent. Live (Rathaa, Oct 2026): the AI's "we'll get back to you" was the last
outbound message and the waiting guest was auto-Lost "no response"."""
from datetime import timedelta

import pytest

from app.services import lead_autopilot_rules as rules
from app.services.lead_autopilot_rules import StageMap
from tests.services._autopilot_fixtures import NOW, lead, msg, settings, tenant


def _decide(db, t, inq):
    return rules.evaluate(db, t.id, inq, StageMap.load(db, t.id), settings(), now=NOW)


@pytest.mark.parametrize("ours", [
    dict(body="We'll get back to you as soon as possible.", is_ai_generated=True, was_approved=True, sent_autonomously=True),
    dict(body="Let me check this with our team.", sender_kind="ai_holding", was_approved=True, sent_autonomously=True),
    dict(body="Hi, just checking in!", sender_kind="playbook", sent_autonomously=True),
    dict(body="Long weekend offer, tell us your dates!", sender_name="Campaign: Sept_long weekend",
         channel_metadata={"kind": "campaign"}),
])
def test_a_guest_waiting_on_us_is_never_lost(db, ours):
    t, s = tenant(db)
    _, inq, conv = lead(db, t.id, s["active"])
    msg(db, t.id, conv, "Any updates on my request?", ago=timedelta(days=16))
    msg(db, t.id, conv, inbound=False, ago=timedelta(days=15), **ours)
    assert _decide(db, t, inq) is None


def test_a_persons_follow_up_then_silence_is_still_lost(db):
    t, s = tenant(db)
    _, inq, conv = lead(db, t.id, s["active"])
    msg(db, t.id, conv, "Hi, caravan for Coorg?", ago=timedelta(days=16))
    msg(db, t.id, conv, "We'll get back to you shortly.", inbound=False, ago=timedelta(days=16) - timedelta(minutes=1),
        is_ai_generated=True, was_approved=True, sent_autonomously=True)
    person = msg(db, t.id, conv, "Hi Kiran, Asha here -- shall I hold the 24th?", inbound=False, ago=timedelta(days=5),
                 sender_name="Asha")
    d = _decide(db, t, inq)
    assert d.rule == "no_reply" and d.evidence[0]["id"] == person.id


def test_another_tenants_contact_never_counts(db):
    t, s = tenant(db)
    g, inq, conv = lead(db, t.id, s["active"])
    msg(db, t.id, conv, "Any updates?", ago=timedelta(days=16))
    other, os_ = tenant(db)
    _, _, other_conv = lead(db, other.id, os_["active"])
    msg(db, other.id, other_conv, "Hi, Asha here", inbound=False, ago=timedelta(days=5), sender_name="Asha")
    assert _decide(db, t, inq) is None
