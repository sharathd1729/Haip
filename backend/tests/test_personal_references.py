"""Yaad references: every point, task, open point, plan and the decision keeps where in the call it was said (a quote +
the second it starts), checked against the transcript, kept through edits only while the words are unchanged, and
carried to reminders and calendar suggestions. Made-up data only."""

from datetime import date

from app.services import personal_calendar as cal
from app.services import personal_calls as pc
from tests.test_personal_calls import MEMORY, _auth, _personal, _tid
from tests.workers import call_analysis_harness as h

TURNS = [
    {"speaker": "SPEAKER_00", "t0": 3.2, "t1": 8.0, "text": "Hello Rishu, about the delegation"},
    {"speaker": "SPEAKER_01", "t0": 41.5, "t1": 47.0, "text": "They arrive on the twenty first, we host till the 23rd"},
    {"speaker": "SPEAKER_00", "t0": 60.0, "t1": 66.0, "text": "Okay I will book the venue by Wednesday"},
]

MODEL = {
    **MEMORY,
    "decision": "Host the delegation from 21 to 23 November.",
    "decision_at": 999,  # the model's guess; the transcript wins
    "decision_quote": "we host till the 23rd",
    "sections": [
        {
            "heading": "Delegation",
            "bullets": [
                {"text": "Arrives on the 21st", "at": 41, "quote": "They arrive on the twenty first"},
                {"text": "Made-up point", "at": 5, "quote": "the price is ten lakh"},  # not in the call
                "a plain string still works",
            ],
        }
    ],
    "action_items": [{"text": "Book the venue", "owner": "me", "at": 60, "quote": "I will book the venue"}],
}


def test_sources_are_checked_against_the_transcript():
    m = pc.ground_refs(pc.normalise(MODEL), TURNS)
    refs = m["refs"]
    assert refs[pc.ref_key("Arrives on the 21st")] == {"at": 41.5, "quote": "They arrive on the twenty first"}
    assert refs[pc.ref_key(m["decision"])]["at"] == 41.5  # timed from the transcript, never the model's 999
    assert refs[pc.ref_key("Book the venue")]["at"] == 60.0
    assert pc.ref_key("Made-up point") not in refs  # a quote that is not in the call is dropped
    assert m["sections"][0]["bullets"] == ["Arrives on the 21st", "Made-up point", "a plain string still works"]


def test_an_edit_keeps_sources_only_for_unchanged_words():
    m = pc.ground_refs(pc.normalise(MODEL), TURNS)
    new, changed = pc.edit(
        m, {"sections": [{"heading": "Delegation", "bullets": ["Arrives on the 21st", "My own note"]}]}, by="u1"
    )
    assert changed == ["sections"]
    assert pc.ref_key("Arrives on the 21st") in new["refs"] and pc.ref_key("My own note") not in new["refs"]
    reread = pc.normalise({**MEMORY, "sections": []}, previous=new)  # a re-read keeps the person's edited sections
    assert pc.ref_key("Arrives on the 21st") in reread["refs"]


def test_reminders_and_calendar_suggestions_carry_the_moment(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    c = h.call(db, tid, ivr_provider="mobile_app", with_transcript=False)
    plan = {
        "what": "Delegation visit",
        "date": "2099-11-21",
        "time": "10:00",
        "place": "Bengaluru",
        "at": 41,
        "quote": "They arrive on the twenty first",
    }
    pc.store(c, pc.ground_refs(pc.normalise({**MODEL, "upcoming": [plan]}), TURNS))
    db.commit()
    rem = client.get("/api/v1/me/reminders", headers=_auth(tenant_and_user)).json()["reminders"]
    assert rem[0]["ref"] == {"at": 60.0, "quote": "I will book the venue"}
    assert cal.suggest_from_calls(db, tid, [c], date(2026, 11, 15)) == 1
    db.commit()
    events = client.get("/api/v1/me/calendar?month=2099-11", headers=_auth(tenant_and_user)).json()["events"]
    assert events[0]["source"] == {"at": 41.5, "quote": "They arrive on the twenty first"}
