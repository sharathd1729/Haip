"""Yaad folders: the person makes folders with keywords and a sorting rule; summarised calls are filed by keyword (no AI) or
by the rule (Gemini Flash-Lite); calls can be put in or taken out by hand, and a call taken out is never filed back;
Unclassified = in no folder; Ask can be limited to one folder. Made-up data only."""

from unittest.mock import patch

from app.models.audit_event import AuditEvent
from app.models.yaad_folder import YaadFolder, YaadFolderCall
from app.services import personal_ask
from app.services import personal_calls as pc
from app.services import personal_folders as pf
from tests.test_personal_calls import MEMORY, _auth, _personal, _remembered_call, _tid
from tests.workers import call_analysis_harness as h


class _Model:
    """get_llm stand-in for the folder rule: files the calls given by number."""

    def __init__(self, calls):
        self.answer, self.seen = {"calls": calls}, []

    def get_llm(self, task, tenant_id=None):
        model = self

        class _A:
            async def complete(self, **kw):
                model.seen.append((task, kw))
                return {"tool_use": model.answer}

        return _A()


def _kitchen(db, tid, **kw):
    c = _remembered_call(db, tid)
    pc.store(c, {**pc.memory_of(c), "title": "Kitchen tiles and budget", "tags": ["Renovation"], **kw})
    db.commit()
    return c


def test_keyword_match_is_whole_word_any_case():
    f = YaadFolder(keywords=["tile", "Ananya Rao"])
    assert pf.keyword_match(f, "Matte TILE stock") and pf.keyword_match(f, "call with ananya rao today")
    assert not pf.keyword_match(f, "a tilted shelf") and not pf.keyword_match(YaadFolder(keywords=[]), "tile")


def test_create_files_by_keyword_and_rule_and_never_refiles_a_call_taken_out(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    headers = _auth(tenant_and_user)
    kitchen, other = _kitchen(db, tid), _remembered_call(db, tid)
    queued = []
    with patch("app.workers.tasks.personal_folders.sort_folder.delay", side_effect=lambda *a: queued.append(a)):
        r = client.post(
            "/api/v1/me/folders",
            headers=headers,
            json={"name": "Home work", "keywords": ["Kitchen", "kitchen", " "], "prompt": "Anything about the house"},
        )
    assert r.status_code == 201 and r.json()["keywords"] == ["Kitchen"] and queued == [(tid, r.json()["id"])]
    folder = db.get(YaadFolder, r.json()["id"])

    model = _Model([{"call": 1, "folders": [1]}, {"call": 2, "folders": [9]}])  # a bad folder number is ignored
    calls = sorted(pf.recent_calls(db, tid, folder), key=lambda c: c.id != other.id)  # `other` = call 1 for the model
    with patch("app.services.personal_folders.get_llm", model.get_llm):
        assert pf.sort_calls(db, tid, calls, [folder], owner_name="Meera") == 2
    db.commit()
    assert model.seen[0][0] == "personal_folder" and "Anything about the house" in model.seen[0][1]["system_prompt"]
    rows = {r.call_id: r.source for r in db.query(YaadFolderCall).filter_by(folder_id=folder.id)}
    assert rows == {kitchen.id: "auto", other.id: "auto"}

    assert client.delete(f"/api/v1/me/folders/{folder.id}/calls/{kitchen.id}", headers=headers).json()["folders"] == []
    with patch("app.services.personal_folders.get_llm", _Model([{"call": 1, "folders": [1]}]).get_llm):
        assert pf.sort_calls(db, tid, [kitchen], [folder], owner_name="Meera") == 0  # taken out = stays out
    back = client.post(f"/api/v1/me/folders/{folder.id}/calls", json={"call_id": kitchen.id}, headers=headers)
    assert back.json()["folders"][0]["name"] == "Home work"

    ids = lambda **p: {c["id"] for c in client.get("/api/v1/me/calls", params=p, headers=headers).json()["calls"]}  # noqa: E731
    assert ids(folder=folder.id) == {kitchen.id, other.id}
    client.delete(f"/api/v1/me/folders/{folder.id}/calls/{other.id}", headers=headers)
    assert ids(folder="unclassified") == {other.id}
    assert client.get(f"/api/v1/me/calls/{kitchen.id}", headers=headers).json()["folders"][0]["id"] == folder.id
    assert client.get("/api/v1/me/folders", headers=headers).json() == {
        "folders": [{**pf.view(folder), "count": 1}],
        "unclassified": 1,
    }


def test_a_failed_rule_check_keeps_keyword_matches(db):
    t = h.tenant(db)
    _personal(db, t.id)
    c = _kitchen(db, t.id)
    folder = pf.create(db, t.id, None, {"name": "Home", "keywords": ["kitchen"], "prompt": "the house"})
    with patch("app.services.personal_folders.get_llm", side_effect=TimeoutError("down")):
        assert pf.sort_calls(db, t.id, [c], [folder], owner_name="Meera") == 1


def test_edit_resorts_only_on_new_keywords_or_rule_and_audits_no_words(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    headers = _auth(tenant_and_user)
    with patch("app.workers.tasks.personal_folders.sort_folder.delay") as resort:
        fid = client.post("/api/v1/me/folders", json={"name": "Secret plans"}, headers=headers).json()["id"]
        client.patch(f"/api/v1/me/folders/{fid}", json={"color": "leaf"}, headers=headers)
        assert resort.call_count == 1
        client.patch(f"/api/v1/me/folders/{fid}", json={"keywords": ["surprise"]}, headers=headers)
        assert resort.call_count == 2
    assert client.patch(f"/api/v1/me/folders/{fid}", json={"name": " "}, headers=headers).status_code == 422
    events = db.query(AuditEvent).filter(AuditEvent.tenant_id == tid, AuditEvent.action.like("yaad_folder.%")).all()
    assert {e.action for e in events} == {"yaad_folder.created", "yaad_folder.updated"}
    assert all("Secret" not in str(e.payload) for e in events)
    assert client.delete(f"/api/v1/me/folders/{fid}", headers=headers).json() == {"deleted": True}
    assert client.get("/api/v1/me/folders", headers=headers).json()["folders"] == []


def test_ask_in_a_folder_reads_only_its_calls(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    kitchen, other = _kitchen(db, tid), _remembered_call(db, tid)
    folder = pf.create(db, tid, None, {"name": "Home"})
    pf.put(db, tid, folder.id, kitchen.id)
    db.commit()
    _, refs = personal_ask.build_context(db, tid, "What did we agree?", folder_id=folder.id)
    assert [r["call_id"] for r in refs] == [kitchen.id] and other.id
    _, every = personal_ask.build_context(db, tid, "What did we agree?")
    assert {r["call_id"] for r in every} == {kitchen.id, other.id}


def test_folders_stay_in_their_workspace_and_are_personal_only(client, db, tenant_and_user):
    headers = _auth(tenant_and_user)
    assert client.get("/api/v1/me/folders", headers=headers).status_code == 403  # a business workspace
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    other = h.tenant(db)
    _personal(db, other.id)
    theirs = pf.create(db, other.id, None, {"name": "Theirs"})
    their_call = _remembered_call(db, other.id)
    mine = pf.create(db, tid, None, {"name": "Mine"})
    db.commit()
    assert client.get("/api/v1/me/folders", headers=headers).json()["folders"][0]["name"] == "Mine"
    assert client.patch(f"/api/v1/me/folders/{theirs.id}", json={"name": "x"}, headers=headers).status_code == 404
    assert (
        client.post(f"/api/v1/me/folders/{mine.id}/calls", json={"call_id": their_call.id}, headers=headers).status_code
        == 404
    )
    assert (
        client.post("/api/v1/me/ask", json={"question": "hi", "folder_id": theirs.id}, headers=headers).status_code
        == 404
    )
    assert MEMORY["title"]
