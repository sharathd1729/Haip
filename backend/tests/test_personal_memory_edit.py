"""Yaad: a person corrects a call's memory (PATCH /me/calls/{id}/memory), sees the changes and undoes one. Edits survive
a re-read by the model; the before/after lives in the memory (erased with the call), the audit row names fields only.
Made-up data only."""

import json

from app.models.audit_event import AuditEvent
from app.models.call import Call
from app.services import personal_calls as pc
from tests.test_personal_calls import MEMORY, _auth, _personal, _remembered_call, _tid
from tests.workers import call_analysis_harness as h


def _url(call_id, tail="memory"):
    return f"/api/v1/me/calls/{call_id}/{tail}"


def test_edit_saves_marks_and_records_history_but_audits_no_words(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    c = _remembered_call(db, tid)
    headers = _auth(tenant_and_user)
    keep = pc.memory_of(c)["action_items"][0]
    body = {
        "title": "Venue booking for the offsite",
        "tags": ["Offsite", "  ", "Venue"],
        "action_items": [
            {"id": keep["id"], "text": keep["text"], "owner": "me", "due": "2026-11-20"},
            {"text": "Call the caterer", "owner": "Kavya"},
        ],
    }
    r = client.patch(_url(c.id), json=body, headers=headers)
    assert r.status_code == 200, r.text
    out = r.json()
    assert sorted(out["changed"]) == ["action_items", "tags", "title"]
    m = out["memory"]
    assert m["title"] == "Venue booking for the offsite" and m["tags"] == ["Offsite", "Venue"]
    assert m["action_items"][0]["id"] == keep["id"] and m["action_items"][0]["due"] == "2026-11-20"
    assert m["action_items"][1]["text"] == "Call the caterer" and m["action_items"][1]["id"] != keep["id"]
    assert set(m["edited"]) == {"title", "tags", "action_items"}
    assert m["history"][0]["before"]["title"] == MEMORY["title"]

    db.expire_all()
    assert pc.memory_of(db.get(Call, c.id))["title"] == "Venue booking for the offsite"
    ev = db.query(AuditEvent).filter_by(tenant_id=tid, action="personal_call.memory_edited").one()
    assert ev.target_id == c.id and sorted(ev.payload["fields"]) == ["action_items", "tags", "title"]
    assert "Venue booking" not in json.dumps(ev.payload) and MEMORY["title"] not in json.dumps(ev.payload)

    hist = client.get(_url(c.id, "history"), headers=headers).json()
    assert hist["changes"][0]["by"] == "you" and hist["changes"][0]["fields"] == out["changed"]

    same = client.patch(_url(c.id), json={"title": "Venue booking for the offsite"}, headers=headers).json()
    assert same["changed"] == [] and db.query(AuditEvent).filter_by(action="personal_call.memory_edited").count() == 1


def test_a_re_read_keeps_the_persons_edits():
    first = pc.normalise(MEMORY)
    edited, changed = pc.edit(first, {"title": "My own title", "decision": ""}, by="u1")
    assert changed == ["title", "decision"]
    again = pc.normalise({**MEMORY, "title": "Model's new title", "decision": "Model decision"}, previous=edited)
    assert again["title"] == "My own title" and again["decision"] == ""
    assert again["history"] == edited["history"] and again["sections"] == first["sections"]  # the rest re-read


def test_undo_puts_back_what_a_change_replaced(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    c = _remembered_call(db, tid)
    headers = _auth(tenant_and_user)
    entry = client.patch(_url(c.id), json={"decision": "Changed my mind"}, headers=headers).json()["memory"]["history"][
        0
    ]
    r = client.post(_url(c.id, f"history/{entry['id']}/undo"), headers=headers)
    assert r.status_code == 200 and r.json()["memory"]["decision"] == pc.normalise(MEMORY)["decision"]
    assert r.json()["memory"]["history"][0]["undo_of"] == entry["id"]
    assert db.query(AuditEvent).filter_by(tenant_id=tid, action="personal_call.memory_undone").count() == 1
    assert client.post(_url(c.id, "history/nope/undo"), headers=headers).status_code == 404


def test_edits_stay_in_their_workspace_and_need_a_summary(client, db, tenant_and_user):
    headers = _auth(tenant_and_user)
    tid = _tid(tenant_and_user)
    theirs = _remembered_call(db, h.tenant(db).id)
    assert client.patch(_url(theirs.id), json={"title": "x"}, headers=headers).status_code == 403  # not personal
    _personal(db, tid)
    assert client.patch(_url(theirs.id), json={"title": "x"}, headers=headers).status_code == 404
    assert client.get(_url(theirs.id, "history"), headers=headers).status_code == 404
    assert pc.memory_of(db.get(Call, theirs.id))["title"] == MEMORY["title"]
    bare = h.call(db, tid, ivr_provider="mobile_app")
    assert client.patch(_url(bare.id), json={"title": "x"}, headers=headers).status_code == 409
    assert client.patch(_url(bare.id), json={"bogus": 1}, headers=headers).status_code == 422
