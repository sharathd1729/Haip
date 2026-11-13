"""Personal workspaces (services/personal_calls.py, endpoints/personal_calls.py): one person's own calls, read like a
NeoSapien memory instead of the hospitality QA score; the /me screens; every call kept from the Calls app."""
import uuid
from unittest.mock import patch

from app.models.call import Call
from app.models.score import CallScore
from app.models.tenant import Tenant
from app.services import personal_calls as pc
from tests.workers import call_analysis_harness as h

MEMORY = {
    "title": "Malaysian delegation visit and wellness pricing",
    "category": "Business",
    "tags": ["Wellness", "Delegation", "Pricing", "Extra", "More", "Too many"],
    "participants": [{"name": "Rishu", "role": "business partner"}, {"name": ""}],
    "decision": "Host the delegation from 21 to 23 November.",
    "sections": [
        {"heading": "Delegation", "bullets": ["Arrives on the 21st", "  "]},
        {"heading": "", "bullets": ["dropped: no heading"]},
    ],
    "action_items": [
        {"text": "Book the venue", "owner": "me", "due": "2026-11-18", "context": "For the delegation"},
        {"text": "Send visiting cards", "owner": "Prashant", "due": "next week"},
        {"text": "  "},
    ],
    "open_points": ["Who pays for travel?"],
    "upcoming": [
        {"what": "Delegation visit", "date": "2099-11-21", "time": "10:00", "place": "Bengaluru"},
        {"what": "No date", "date": "soon"},
    ],
    "learning": "Delegations decide on the first day.",
    "category_bogus": "ignored",
}


def _personal(db, tenant_id):
    t = db.get(Tenant, tenant_id)
    t.brand_config = {**(t.brand_config or {}), pc.MODE_KEY: pc.PERSONAL}
    db.commit()


def _tid(tenant_and_user):
    t = tenant_and_user["tenant"]
    return t["id"] if isinstance(t, dict) else t.id


def _auth(tenant_and_user):
    return {"Authorization": f"Bearer {tenant_and_user['access_token']}"}


def _run(db, tenant_id, call_id, llm):
    with patch("app.services.personal_calls.get_llm", llm.get_llm):
        return h.run(db, tenant_id, call_id, llm)


# ─── The read ────────────────────────────────────────────────────────────────


def test_normalise_cleans_the_answer_and_keeps_done_reminders_on_a_re_read():
    m = pc.normalise(MEMORY)
    assert m["version"] == pc.VERSION and m["category"] == "Business" and len(m["tags"]) == 5
    assert m["participants"] == [{"name": "Rishu", "role": "business partner"}]
    assert m["sections"] == [{"heading": "Delegation", "bullets": ["Arrives on the 21st"]}]
    assert [a["text"] for a in m["action_items"]] == ["Book the venue", "Send visiting cards"]
    assert m["action_items"][0]["due"] == "2026-11-18" and m["action_items"][1]["due"] == ""  # "next week" is no date
    assert [u["what"] for u in m["upcoming"]] == ["Delegation visit"]
    assert pc.normalise({**MEMORY, "category": "Gossip"})["category"] == "Other"

    first = m["action_items"][0]
    m["action_items"][0] = {**first, "done": True, "done_at": "2026-11-14T10:00:00+00:00"}
    again = pc.normalise(MEMORY, previous=m)
    assert again["action_items"][0]["done"] is True and again["action_items"][0]["id"] == first["id"]
    assert again["action_items"][1]["done"] is False


def test_share_text_is_whatsapp_ready():
    text = pc.share_text(pc.normalise(MEMORY), contact="Rishu", when="13 Nov 2026")
    assert text.startswith("*Malaysian delegation visit and wellness pricing*\nRishu · 13 Nov 2026")
    assert "*Decision:* Host the delegation" in text and "*Delegation*\n*   Arrives on the 21st" in text
    assert "*   Book the venue (Owner: Me, by 2026-11-18)" in text and "(Owner: Prashant)" in text
    assert "*Open Points*" in text and text.endswith(pc.SHARE_FOOTER)


def test_personal_workspace_call_gets_a_memory_not_a_qa_score(db):
    t = h.tenant(db)
    _personal(db, t.id)
    c = h.call(db, t.id, ivr_provider="mobile_app")
    llm = h.ScriptedLLM(tool_use=MEMORY)
    effects = _run(db, t.id, c.id, llm)
    call = db.get(Call, c.id)
    assert call.ai_score_status == "done" and call.ai_score is None
    assert pc.memory_of(call)["title"] == MEMORY["title"]
    assert db.query(CallScore).filter_by(call_id=c.id).count() == 0
    assert effects.autopilot == [] and effects.triggers == [] and effects.pushes == []  # no sales effects
    assert len(llm.calls) == 1 and "remember_call" in str(llm.calls[0][1]["tools"])


def test_business_workspace_still_gets_the_qa_read(db):
    t = h.tenant(db)
    c = h.call(db, t.id)
    _run(db, t.id, c.id, h.ScriptedLLM(tool_use=h.answer()))
    call = db.get(Call, c.id)
    assert pc.memory_of(call) is None and call.ai_score_status == "done"


def test_a_failed_personal_read_is_marked_failed_for_recovery(db):
    t = h.tenant(db)
    _personal(db, t.id)
    c = h.call(db, t.id, ivr_provider="mobile_app")
    with patch.object(h.task_mod.analyze_call, "retry", side_effect=RuntimeError("retry")):
        try:
            _run(db, t.id, c.id, h.ScriptedLLM(error=TimeoutError("model down")))
        except RuntimeError:
            pass
    db.expire_all()  # the forced retry skipped the harness's own refresh
    assert db.get(Call, c.id).ai_score_status == "failed" and pc.memory_of(db.get(Call, c.id)) is None


# ─── /me screens ─────────────────────────────────────────────────────────────


def _remembered_call(db, tenant_id, **kw):
    c = h.call(db, tenant_id, ivr_provider="mobile_app", recording_s3_key=f"{tenant_id}/calls/x.mp3", **kw)
    pc.store(c, pc.normalise(MEMORY))
    c.transcription_status = "done"
    db.commit()
    return c


def test_me_screens_list_detail_reminders_and_done(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    c = _remembered_call(db, tid)
    h.call(db, tid, ivr_provider="mobile_app", with_transcript=False)  # no recording yet
    headers = _auth(tenant_and_user)

    page = client.get("/api/v1/me/calls", headers=headers).json()
    rows = {r["id"]: r for r in page["calls"]}
    assert rows[c.id]["status"] == "ready" and rows[c.id]["title"] == MEMORY["title"] and rows[c.id]["reminders_open"] == 2
    assert sorted(r["status"] for r in page["calls"]) == ["no_recording", "ready"]
    assert [u["what"] for u in page["upcoming"]] == ["Delegation visit"] and page["upcoming"][0]["call_id"] == c.id

    detail = client.get(f"/api/v1/me/calls/{c.id}", headers=headers).json()
    assert detail["memory"]["decision"].startswith("Host") and detail["share_text"].endswith(pc.SHARE_FOOTER)
    assert detail["transcript"] and detail["transcript"][0]["text"]

    open_ = client.get("/api/v1/me/reminders", headers=headers).json()["reminders"]
    assert [r["text"] for r in open_] == ["Book the venue", "Send visiting cards"]  # dated first
    rid = open_[0]["id"]
    r = client.patch(f"/api/v1/me/calls/{c.id}/reminders/{rid}", json={"done": True}, headers=headers)
    assert r.status_code == 200 and r.json()["done"] is True
    assert [x["text"] for x in client.get("/api/v1/me/reminders?status=done", headers=headers).json()["reminders"]] == ["Book the venue"]
    assert client.patch(f"/api/v1/me/calls/{c.id}/reminders/nope", json={"done": True}, headers=headers).status_code == 404


def test_me_screens_are_only_for_personal_workspaces(client, tenant_and_user):
    assert client.get("/api/v1/me/calls", headers=_auth(tenant_and_user)).status_code == 403


def test_me_screens_never_show_another_workspaces_call(client, db, tenant_and_user):
    tid = _tid(tenant_and_user)
    _personal(db, tid)
    other = h.tenant(db)
    theirs = _remembered_call(db, other.id)
    headers = _auth(tenant_and_user)
    assert client.get(f"/api/v1/me/calls/{theirs.id}", headers=headers).status_code == 404
    assert client.get("/api/v1/me/calls", headers=headers).json()["calls"] == []
    rid = pc.memory_of(theirs)["action_items"][0]["id"]
    assert client.patch(f"/api/v1/me/calls/{theirs.id}/reminders/{rid}", json={"done": True}, headers=headers).status_code == 404


def test_workspace_context_says_personal(client, db, tenant_and_user):
    headers = _auth(tenant_and_user)
    assert client.get("/api/v1/workspace/context", headers=headers).json()["mode"] == "business"
    _personal(db, _tid(tenant_and_user))
    assert client.get("/api/v1/workspace/context", headers=headers).json()["mode"] == "personal"


# ─── Capture ─────────────────────────────────────────────────────────────────


def test_personal_workspace_keeps_unknown_numbers_at_any_hour(client, db, tenant_and_user, monkeypatch):
    from tests.test_mobile_devices import _call, _register, _user, queued  # noqa: F401

    tid = _tid(tenant_and_user)
    _, staff_h = _user(db, tid)
    dev = _register(client, staff_h, settings={"unknown_numbers": "never"})
    sent = []
    monkeypatch.setattr("app.workers.tasks.call_ingest.ingest_call.delay", lambda *a: sent.append(a))
    body = {"calls": [_call(number="+919811112222", cid=uuid.uuid4().hex[:8])]}
    auth = {"Authorization": f"Bearer {dev['token']}"}
    assert client.post("/api/v1/device-calls", json=body, headers=auth).json()["counts"] == {"skipped_unknown_number": 1}
    _personal(db, tid)
    body = {"calls": [_call(number="+919811113333", cid=uuid.uuid4().hex[:8])]}
    assert client.post("/api/v1/device-calls", json=body, headers=auth).json()["counts"] == {"queued": 1}
