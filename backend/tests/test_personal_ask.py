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
    llm = h.ScriptedLLM(tool_use={"answer": "*Venue*\n* Lakeside, if 12 Dec is free", "call_refs": [1, 1, 7, "x"]})
    with patch("app.services.personal_ask.get_llm", llm.get_llm):
        out = ask.answer(db, t.id, "Which venue?", "Arjun")
    assert out["answer"].startswith("*Venue*") and [s["title"] for s in out["sources"]] == ["Wedding venues"]
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
    llm = h.ScriptedLLM(tool_use={"answer": "Book the venue by Wednesday.", "call_refs": [1]})
    with store.patches()[0], store.patches()[1], store.patches()[2], \
         patch("app.workers.tasks.personal_ask.ask.delay", side_effect=lambda *a: queued.append(a)), \
         patch("app.services.personal_ask.get_llm", llm.get_llm):
        r = client.post("/api/v1/me/ask", json={"question": "Action items?"}, headers=_auth(tenant_and_user))
        assert r.status_code == 202 and llm.calls == []          # nothing ran inside the request
        job = r.json()["id"]
        assert client.get(f"/api/v1/me/ask/{job}", headers=_auth(tenant_and_user)).json()["status"] == "pending"
        from app.workers.tasks import personal_ask as task_mod
        with patch.object(task_mod, "SessionLocal", return_value=SASession(bind=db.connection())):
            task_mod.ask.run(*queued[0])
        done = client.get(f"/api/v1/me/ask/{job}", headers=_auth(tenant_and_user)).json()
    assert done["status"] == "done" and done["answer"] == "Book the venue by Wednesday."
    assert done["sources"][0]["title"] == "Wedding venues" and "model_used" not in done


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
