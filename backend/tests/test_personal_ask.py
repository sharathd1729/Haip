"""Ask Yaad (services/personal_ask.py, tasks personal.ask, POST/GET /me/ask): answers only from the person's own call
memories, cites the calls it used, never runs the model inside the request, stays inside the workspace."""
import json
import uuid
from unittest.mock import patch

from sqlalchemy.orm import Session as SASession

from app.models.guest import Guest
from app.services import personal_ask as ask
from app.services import personal_calls as pc
from tests.test_personal_calls import MEMORY, _auth, _personal, _tid
from tests.workers import call_analysis_harness as h


def _remembered(db, tenant_id, name, title):
    g = Guest(id=str(uuid.uuid4()), tenant_id=tenant_id, name=name)
    db.add(g)
    db.commit()
    c = h.call(db, tenant_id, ivr_provider="mobile_app", guest_id=g.id, with_transcript=False)
    pc.store(c, pc.normalise({**MEMORY, "title": title}))
    db.commit()
    return c


class _Store:
    def __init__(self):
        self.data = {}

    def patches(self):
        return [
            patch("app.core.cache.get_cached", side_effect=lambda k: self.data.get(k)),
            patch("app.core.cache.set_cached", side_effect=lambda k, v, ttl=300: self.data.__setitem__(k, json.loads(json.dumps(v)))),
            patch("app.core.cache.incr", return_value=1),
        ]


def test_context_puts_the_named_person_first(db):
    t = h.tenant(db)
    _personal(db, t.id)
    _remembered(db, t.id, "Meera Iyer", "Wedding venues")
    _remembered(db, t.id, "Rohan Shetty", "Cafe lease")
    notes, refs = ask.build_context(db, t.id, "What did Rohan say about the lease?")
    assert refs[0]["contact"] == "Rohan Shetty" and notes.startswith("[1]") and "Cafe lease" in notes.split("\n\n")[0]
    assert "Action (me, due 2026-11-18): Book the venue" in notes


def test_answer_maps_the_cited_calls_and_ignores_bad_refs(db):
    t = h.tenant(db)
    _personal(db, t.id)
    _remembered(db, t.id, "Meera Iyer", "Wedding venues")
    llm = h.ScriptedLLM(
        tool_use={
            "answer": "*Venue*\n* Lakeside, if 12 Dec is free [1][7]",
            "citations": [{"call": 1, "note": "Book the venue"}, {"call": 7}, {"call": "x"}],
            "followups": ["Who pays for travel?", "  "],
        }
    )
    with patch("app.services.personal_ask.get_llm", llm.get_llm):
        out = ask.answer(db, t.id, "Which venue?", "Arjun")
    assert out["answer"] == "*Venue*\n* Lakeside, if 12 Dec is free [1]"  # [7] was never given to the model
    assert [(s["n"], s["title"]) for s in out["sources"]] == [(1, "Wedding venues")]
    assert out["followups"] == ["Who pays for travel?"]
    assert "Arjun" in llm.calls[0][1]["system_prompt"] and "QUESTION\nWhich venue?" in llm.calls[0][1]["user_message"]


def test_no_calls_yet_needs_no_model(db):
    t = h.tenant(db)
    _personal(db, t.id)
    with patch("app.services.personal_ask.get_llm", side_effect=AssertionError("no model call")):
        assert ask.answer(db, t.id, "Summarise today", "Arjun")["sources"] == []


def test_ask_endpoint_queues_then_the_task_answers(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    _remembered(db, tid, "Meera Iyer", "Wedding venues")
    store, queued = _Store(), []
    llm = h.ScriptedLLM(tool_use={"answer": "Book the venue by Wednesday [1].", "citations": [{"call": 1}]})
    with store.patches()[0], store.patches()[1], store.patches()[2], \
         patch("app.workers.tasks.personal_ask.ask.delay", side_effect=lambda *a: queued.append(a)), \
         patch("app.services.personal_ask.get_llm", llm.get_llm):
        r = client.post("/api/v1/me/ask", json={"question": "Action items?"}, headers=_auth(tenant_and_user))
        assert r.status_code == 202 and llm.calls == []          # nothing ran inside the request
        job = r.json()["id"]
        first = client.get(f"/api/v1/me/ask/{job}", headers=_auth(tenant_and_user)).json()
        assert first["status"] == "pending" and first["stage"] == "queued"
        from app.workers.tasks import personal_ask as task_mod
        stages, finish = [], ask.finish_job
        with patch.object(task_mod, "SessionLocal", return_value=SASession(bind=db.connection())),              patch.object(ask, "finish_job", side_effect=lambda t, j, d: (stages.append(d.get("stage")), finish(t, j, d))):
            task_mod.ask.run(*queued[0])
        assert stages == ["reading", "writing", None]  # the screen shows each step, then the answer
        done = client.get(f"/api/v1/me/ask/{job}", headers=_auth(tenant_and_user)).json()
    assert done["status"] == "done" and done["answer"] == "Book the venue by Wednesday [1]."
    assert done["sources"][0]["title"] == "Wedding venues" and "model_used" not in done
    chat = client.get(f"/api/v1/me/asks/{r.json()['session_id']}", headers=_auth(tenant_and_user)).json()
    assert [t["question"] for t in chat["turns"]] == ["Action items?"] and chat["turns"][0]["id"] == done["turn"]["id"]


def test_ask_is_personal_only_capped_and_stays_in_its_workspace(client, db, tenant_and_user):
    headers = _auth(tenant_and_user)
    assert client.post("/api/v1/me/ask", json={"question": "Hi"}, headers=headers).status_code == 403
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    with patch("app.core.cache.incr", return_value=ask.DAILY_LIMIT + 1):
        assert client.post("/api/v1/me/ask", json={"question": "Hi"}, headers=headers).status_code == 429
    store = _Store()
    other = h.tenant(db)
    store.data[ask._job_key(other.id, "abc")] = {"status": "done", "question": "theirs", "answer": "secret"}
    with store.patches()[0]:
        assert client.get("/api/v1/me/ask/abc", headers=headers).status_code == 404


# ─── References ([n] citations) ─────────────────────────────────────────────


def test_cite_renumbers_in_reading_order_and_finds_the_moment():
    memory = pc.normalise(
        {
            **MEMORY,
            "sections": [{"heading": "Venue", "bullets": [{"text": "Lakeside is free on 12 Dec", "at": 40, "quote": "lakeside is free"}]}],
        }
    )
    refs = [
        {"call_id": "a", "title": "A", "contact": "Meera", "at": "2026-11-10T10:00:00+00:00", "_memory": memory},
        {"call_id": "b", "title": "B", "contact": "Rohan", "at": "2026-11-11T10:00:00+00:00", "_memory": {}},
    ]
    text, sources = ask.cite(
        "Rohan agreed [2]. Lakeside is free on the 12th [1][2]. Bad [9].",
        [{"call": 1, "note": "Venue: Lakeside is free on 12 Dec"}],
        refs,
    )
    assert text == "Rohan agreed [1]. Lakeside is free on the 12th [2][1]. Bad ."
    assert [s["call_id"] for s in sources] == ["b", "a"] and "_memory" not in sources[0]
    assert sources[1]["t"] == 40.0 and sources[1]["quote"] == "lakeside is free"
    assert ask.plain(text) == "Rohan agreed. Lakeside is free on the 12th. Bad ."


def test_follow_up_in_a_chat_sends_the_earlier_turns(db):
    t = h.tenant(db)
    _personal(db, t.id)
    _remembered(db, t.id, "Meera Iyer", "Wedding venues")
    llm = h.ScriptedLLM(tool_use={"answer": "She wants Lakeside [1].", "citations": [{"call": 1}]})
    history = [{"question": "What did Meera say?", "answer": "Venue by Wednesday [1]."}]
    with patch("app.services.personal_ask.get_llm", llm.get_llm):
        ask.answer(db, t.id, "And the date?", "Arjun", history=history)
    sent = llm.calls[0][1]["user_message"]
    assert sent.startswith("EARLIER IN THIS CHAT") and "A: Venue by Wednesday." in sent  # markers stripped


# ─── Chats ──────────────────────────────────────────────────────────────────


def test_chats_list_open_delete_and_stay_in_their_workspace(client, db, tenant_and_user):
    from app.models.audit_event import AuditEvent

    tid = _tid(tenant_and_user)
    headers = _auth(tenant_and_user)
    assert client.get("/api/v1/me/asks", headers=headers).status_code == 403  # business workspace
    _personal(db, tid)
    mine = ask.new_session(db, tid, None, "What did Meera say?", None)
    ask.add_turn(mine, "What did Meera say?", {"answer": "Lakeside [1].", "sources": [{"n": 1, "call_id": "x"}]})
    ask.new_session(db, tid, None, "never answered", None)  # no turn yet: not listed
    other = h.tenant(db)
    theirs = ask.new_session(db, other.id, None, "theirs", None)
    ask.add_turn(theirs, "theirs", {"answer": "secret"})
    db.commit()
    chats = client.get("/api/v1/me/asks", headers=headers).json()["chats"]
    assert [c["title"] for c in chats] == ["What did Meera say?"] and chats[0]["turns_count"] == 1
    assert client.get(f"/api/v1/me/asks/{theirs.id}", headers=headers).status_code == 404
    assert client.post("/api/v1/me/ask", json={"question": "x", "session_id": theirs.id}, headers=headers).status_code == 404
    turn = mine.turns[0]["id"]
    pdf = client.get(f"/api/v1/me/asks/{mine.id}/turns/{turn}/pdf", headers=headers)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and b"/AcroForm" in pdf.content
    assert client.delete(f"/api/v1/me/asks/{mine.id}", headers=headers).json() == {"deleted": True}
    assert db.query(AuditEvent).filter_by(action="yaad_ask.deleted", target_id=mine.id).count() == 1
    assert client.get(f"/api/v1/me/asks/{theirs.id}", headers=headers).status_code == 404


def test_suggestions_come_from_recent_calls(db):
    t = h.tenant(db)
    _personal(db, t.id)
    assert ask.suggestions(db, t.id) == []
    _remembered(db, t.id, "Meera Iyer", "Wedding venues")
    out = ask.suggestions(db, t.id)
    assert "What did I agree with Meera Iyer?" in out and "What do I need to do this week?" in out and len(out) <= 4
