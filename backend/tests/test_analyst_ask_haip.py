"""Ask HAIP inside the AI Executive (POST/GET /analyst/ask-haip, task analyst.ask_haip): owner-only, behind the ask_haip
module, queued (no model call in the request), answered by the free-form analyst, never readable by another workspace."""
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session as SASession

from app.models.ask_haip import AskHaipFreeformQuery
from app.models.user import User, UserRole
from app.services.analyst import ask_haip_jobs as jobs

URL = "/api/v1/analyst/ask-haip"


def _tid(tu):
    t = tu["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _auth(tu):
    return {"Authorization": f"Bearer {tu['access_token']}"}


def _entitle(db, tid):
    from app.models.module import Module, WorkspaceModule

    mod = db.query(Module).filter_by(code="ask_haip").first()
    if mod is None:
        mod = Module(id=str(uuid.uuid4()), code="ask_haip", name="Ask HAIP")
        db.add(mod)
        db.flush()
    db.add(WorkspaceModule(id=str(uuid.uuid4()), workspace_id=tid, module_id=mod.id, enabled=True))
    db.commit()
    from app.core import cache

    cache.ctx_bust(tid)  # the workspace context (active modules) is cached


class _Store:
    def __init__(self):
        self.data = {}

    def __enter__(self):
        self._p = [
            patch("app.core.cache.get_cached", side_effect=self.data.get),
            patch("app.core.cache.set_cached",
                  side_effect=lambda k, v, ttl=300: self.data.__setitem__(k, json.loads(json.dumps(v, default=str)))),
            patch("app.core.cache.incr", return_value=1),
        ]
        for p in self._p:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self._p:
            p.stop()


ANSWER = {"narrative": "You had 42 leads this month, most from Instagram.", "rows": [{"source": "META_IG", "n": 30}],
          "row_count": 1, "chart": None, "sql": "SELECT ..."}


def test_owner_asks_and_the_task_answers(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _entitle(db, tid)
    queued = []
    with _Store(), patch("app.workers.tasks.analyst_tasks.ask_haip.delay", side_effect=lambda *a: queued.append(a)), \
         patch("app.services.ask_haip_freeform_service.answer_freeform_question", new=AsyncMock(return_value=ANSWER)) as model:
        r = client.post(URL, json={"question": "How many leads this month by source?"}, headers=_auth(tenant_and_user))
        assert r.status_code == 202 and model.await_count == 0          # nothing ran inside the request
        job = r.json()["id"]
        assert client.get(f"{URL}/{job}", headers=_auth(tenant_and_user)).json()["status"] == "pending"
        from app.workers.tasks import analyst_tasks
        with patch.object(analyst_tasks, "SessionLocal", return_value=SASession(bind=db.connection())):
            analyst_tasks.ask_haip.run(*queued[0])
        done = client.get(f"{URL}/{job}", headers=_auth(tenant_and_user)).json()
    assert done["status"] == "done" and done["narrative"].startswith("You had 42 leads") and done["rows"][0]["n"] == 30
    assert model.await_args.kwargs["question"] == "How many leads this month by source?"


def test_a_rejected_question_comes_back_as_a_plain_failure():
    out = jobs.result_of("Delete everything", {"narrative": None, "error": "Only read questions are allowed."})
    assert out == {"status": "failed", "question": "Delete everything", "error": "Only read questions are allowed."}
    assert jobs.result_of("x", {})["error"].startswith("HAIP couldn't answer")


def test_owner_only_module_gated_capped_and_tenant_isolated(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    headers = _auth(tenant_and_user)
    assert client.post(URL, json={"question": "How many leads?"}, headers=headers).status_code == 403   # module off
    _entitle(db, tid)
    with patch("app.core.cache.incr", return_value=jobs.DAILY_LIMIT + 1):
        assert client.post(URL, json={"question": "How many leads?"}, headers=headers).status_code == 429
    with _Store() as s:
        s.data[jobs._key(str(uuid.uuid4()), "abc")] = {"status": "done", "narrative": "theirs"}
        assert client.get(f"{URL}/abc", headers=headers).status_code == 404
    for u in db.query(User).filter_by(tenant_id=tid):
        u.role = UserRole.MANAGER
    db.commit()
    assert client.post(URL, json={"question": "How many leads?"}, headers=headers).status_code == 403


def test_recent_lists_this_workspaces_answered_questions_once(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _entitle(db, tid)
    for q, status in [("Leads by source", "ok"), ("leads by source", "ok"), ("Bad one", "rejected")]:
        db.add(AskHaipFreeformQuery(id=str(uuid.uuid4()), tenant_id=tid, question=q, status=status))
    db.add(AskHaipFreeformQuery(id=str(uuid.uuid4()), tenant_id=str(uuid.uuid4()), question="Theirs", status="ok"))
    db.commit()
    r = client.get(f"{URL}/recent", headers=_auth(tenant_and_user))
    assert [x["question"].lower() for x in r.json()["questions"]] == ["leads by source"]


@pytest.mark.parametrize("q", ["", "hi"])
def test_too_short_questions_are_refused(client, db, tenant_and_user, q):
    _entitle(db, _tid(tenant_and_user))
    assert client.post(URL, json={"question": q}, headers=_auth(tenant_and_user)).status_code == 422
