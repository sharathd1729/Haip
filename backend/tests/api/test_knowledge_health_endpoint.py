"""GET /knowledge/health: every entry the bot cannot use and why, and what replies got from the knowledge base."""

import uuid

from app.models.conversation import Message
from app.services import knowledge_service as ks
from tests.api.test_knowledge_freshness_endpoints import _entry
from tests.test_business_data import _workspace
from tests.test_increment1_defect_specs import _conv, _h

URL = "/api/v1/knowledge/health"


def _reply(db, tid, conv, kb):
    db.add(
        Message(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            conversation_id=conv.id,
            direction="outbound",
            channel="whatsapp",
            body="ok",
            is_ai_generated=True,
            channel_metadata={"kb": kb},
        )
    )
    db.commit()


def test_health_lists_each_unusable_entry_with_its_reason_and_unused_entries(db, client):
    w = _workspace(db)
    used = _entry(db, w.t.id, content="Towels are provided")
    unused = _entry(db, w.t.id, content="Pets are welcome")
    waiting = _entry(db, w.t.id, source="instagram", review_status="pending", content="Mysore Dasara route")
    gave_up = _entry(
        db, w.t.id, embedding_status="failed", embedding_attempts=ks.MAX_AUTO_ATTEMPTS, embedding_error="NIM 504"
    )
    _entry(db, w.t.id, is_active=False, content="old offer")
    _, conv = _conv(db, w.t.id)
    _reply(db, w.t.id, conv, {"status": "ok", "hits": [{"id": used.id, "score": 0.7}]})
    _reply(db, w.t.id, conv, {"status": "embedding_unavailable", "hits": []})

    r = client.get(URL, headers=_h(w.owner))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["usable"] == 2 and body["blocked"] == 2
    assert body["counts"] == {"waiting_approval": 1, "gave_up": 1, "never_used": 1, "off": 1}
    assert body["replies"] == {"recorded": 2, "by_search_status": {"ok": 1, "embedding_unavailable": 1}}
    rows = {e["id"]: e for e in body["entries"]}
    assert [x["code"] for x in rows[waiting.id]["reasons"]] == ["waiting_approval"]
    assert rows[gave_up.id]["reasons"][0]["code"] == "gave_up" and rows[gave_up.id]["error"] == "NIM 504"
    assert rows[unused.id]["reasons"][0]["code"] == "never_used"
    assert used.id not in rows
    assert body["entries"][-1]["id"] == unused.id  # blocked entries first
    assert client.get(URL, headers=_h(w.mgr)).status_code == 200


def test_health_is_refused_to_other_roles(db, client):
    w = _workspace(db)
    assert client.get(URL, headers=_h(w.ro)).status_code == 403


def test_health_never_shows_another_workspace(db, client):
    a, b = _workspace(db), _workspace(db)
    _entry(db, b.t.id, review_status="pending", content="theirs")
    body = client.get(URL, headers=_h(a.owner)).json()
    assert body["entries"] == [] and body["counts"] == {}
