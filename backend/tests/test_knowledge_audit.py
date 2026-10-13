"""K-0: every change to the descriptive knowledge base leaves one chained audit row (who, what, previous and new value).

Create / edit / approve / reject / deactivate / delete / reindex / upload / crawl are all covered; a no-op edit writes nothing; a
reader cannot change anything; tenants only see their own history.
"""
import io
from unittest.mock import MagicMock, patch

import pytest

from app.models.audit_event import AuditEvent
from app.models.knowledge import KnowledgeEntry
from tests.test_business_data import _workspace
from tests.test_increment1_defect_specs import _h


@pytest.fixture(autouse=True)
def _no_embedding_dispatch(monkeypatch):
    monkeypatch.setattr("app.core.url_safety.assert_public_url", lambda *a, **k: None)
    with patch("app.workers.tasks.embed_knowledge.embed_entry.delay", MagicMock()):
        yield


@pytest.fixture()
def w(db):
    return _workspace(db)


def rows(db, tid, action=None):
    db.flush()
    q = db.query(AuditEvent).filter(AuditEvent.tenant_id == tid, AuditEvent.action.like("kb.%"))
    if action:
        q = q.filter(AuditEvent.action == f"kb.{action}")
    return q.order_by(AuditEvent.created_at).all()


def make(client, w, **over):
    body = {"category": "faq", "question": "Is there Wi-Fi?", "content": "Yes, in the caravan.", **over}
    r = client.post("/api/v1/knowledge", json=body, headers=_h(w.owner))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_create_edit_approve_deactivate_and_delete_each_leave_one_row_with_the_actor_and_values(db, client, w):
    eid = make(client, w)
    created = rows(db, w.t.id, "created")
    assert len(created) == 1 and created[0].actor_user_id == w.owner.id and created[0].target_id == eid
    assert created[0].payload["values"]["content"] == "Yes, in the caravan."

    h = _h(w.owner)
    assert client.patch(f"/api/v1/knowledge/{eid}", json={"content": "Yes, free Wi-Fi in every caravan."}, headers=h).status_code == 200
    upd = rows(db, w.t.id, "updated")
    assert len(upd) == 1 and upd[0].payload["changes"] == {"content": {"from": "Yes, in the caravan.", "to": "Yes, free Wi-Fi in every caravan."}}

    client.patch(f"/api/v1/knowledge/{eid}", json={"review_status": "rejected"}, headers=h)
    client.patch(f"/api/v1/knowledge/{eid}", json={"review_status": "approved", "is_active": False}, headers=h)
    last = rows(db, w.t.id, "updated")[-1].payload["changes"]
    assert last == {"is_active": {"from": True, "to": False}, "review_status": {"from": "rejected", "to": "approved"}}
    assert len(rows(db, w.t.id, "updated")) == 3

    assert client.delete(f"/api/v1/knowledge/{eid}", headers=h).status_code == 204
    gone = rows(db, w.t.id, "deleted")
    assert len(gone) == 1 and gone[0].payload["deleted_values"]["content"].startswith("Yes, free Wi-Fi") and gone[0].actor_user_id == w.owner.id
    assert db.query(KnowledgeEntry).filter_by(id=eid).first() is None                       # the text survives only in the audit trail


def test_an_edit_that_changes_nothing_writes_no_row_and_the_chain_stays_intact(db, client, w):
    eid = make(client, w)
    before = len(rows(db, w.t.id))
    assert client.patch(f"/api/v1/knowledge/{eid}", json={"content": "Yes, in the caravan.", "priority": 0}, headers=_h(w.owner)).status_code == 200
    assert len(rows(db, w.t.id)) == before
    chain = db.query(AuditEvent).filter_by(tenant_id=w.t.id).order_by(AuditEvent.created_at).all()
    assert all(chain[i].prev_hash == chain[i - 1].hash for i in range(1, len(chain)))


def test_reindex_ingest_and_crawl_are_recorded(db, client, w):
    eid = make(client, w)
    h = _h(w.owner)
    assert client.post(f"/api/v1/knowledge/{eid}/reembed", headers=h).status_code == 200
    assert rows(db, w.t.id, "reindex_requested")[0].target_id == eid

    with patch("app.services.media_storage.upload_knowledge_file", return_value="k/1"):
        r = client.post("/api/v1/knowledge/upload", files={"file": ("rates.txt", io.BytesIO(b"Check-in is from 2 pm. " * 20), "text/plain")}, headers=h)
    assert r.status_code == 201, r.text
    ing = rows(db, w.t.id, "ingested")
    assert ing[0].payload["source"] == "document" and ing[0].payload["filename"] == "rates.txt" and ing[0].payload["entries_created"] >= 1

    with patch("app.services.knowledge_ingest.fetch_url_text", return_value="Pets are welcome on request. " * 10):
        r = client.post("/api/v1/knowledge/crawl", json={"urls": ["https://example.com/faq"]}, headers=h)
    assert r.status_code == 201, r.text
    assert rows(db, w.t.id, "ingested")[-1].payload["urls"] == ["https://example.com/faq"]


def test_a_reader_cannot_change_the_knowledge_base_and_no_row_is_written(db, client, w):
    eid = make(client, w)
    n = len(rows(db, w.t.id))
    ro = _h(w.ro)
    assert client.patch(f"/api/v1/knowledge/{eid}", json={"content": "Hacked"}, headers=ro).status_code == 403
    assert client.delete(f"/api/v1/knowledge/{eid}", headers=ro).status_code == 403
    assert len(rows(db, w.t.id)) == n and db.query(KnowledgeEntry).filter_by(id=eid).one().content == "Yes, in the caravan."


def test_another_tenants_entry_is_not_found_and_leaves_no_row(db, client, w):
    other = _workspace(db)
    eid = make(client, other)
    n = len(rows(db, other.t.id))
    assert client.patch(f"/api/v1/knowledge/{eid}", json={"content": "x"}, headers=_h(w.owner)).status_code == 404
    assert client.delete(f"/api/v1/knowledge/{eid}", headers=_h(w.owner)).status_code == 404
    assert len(rows(db, other.t.id)) == n and rows(db, w.t.id) == []


# ─── K-1: history and rollback, built on the audit trail ──────────────────────────────────────────────────

def test_history_lists_each_change_with_its_previous_wording_and_survives_deletion(db, client, w):
    eid = make(client, w)
    h = _h(w.owner)
    client.patch(f"/api/v1/knowledge/{eid}", json={"content": "Wi-Fi is free."}, headers=h)
    client.patch(f"/api/v1/knowledge/{eid}", json={"content": "Wi-Fi is free for guests only.", "priority": 5}, headers=h)
    hist = client.get(f"/api/v1/knowledge/{eid}/history", headers=h).json()
    assert [x["action"] for x in hist] == ["updated", "updated", "created"]                    # newest first
    assert hist[0]["changes"]["content"] == {"from": "Wi-Fi is free.", "to": "Wi-Fi is free for guests only."}
    assert hist[0]["actor_user_id"] == w.owner.id
    client.delete(f"/api/v1/knowledge/{eid}", headers=h)
    assert [x["action"] for x in client.get(f"/api/v1/knowledge/{eid}/history", headers=h).json()][0] == "deleted"


def test_rollback_restores_the_earlier_wording_through_the_normal_edit_path(db, client, w):
    eid = make(client, w)
    h = _h(w.owner)
    client.patch(f"/api/v1/knowledge/{eid}", json={"content": "Wi-Fi is free for guests only.", "priority": 5}, headers=h)
    event = client.get(f"/api/v1/knowledge/{eid}/history", headers=h).json()[0]
    r = client.post(f"/api/v1/knowledge/{eid}/rollback", json={"event_id": event["id"]}, headers=h)
    assert r.status_code == 200, r.text
    entry = db.query(KnowledgeEntry).filter_by(id=eid).one()
    db.refresh(entry)
    assert entry.content == "Yes, in the caravan." and entry.priority == 0
    assert entry.embedding_status == "pending"                                                 # restored text is re-indexed before the AI uses it
    assert [x["action"] for x in client.get(f"/api/v1/knowledge/{eid}/history", headers=h).json()][:2] == ["rolled_back", "updated"]


def test_rollback_refuses_unknown_events_other_tenants_readers_and_truncated_history(db, client, w):
    eid = make(client, w)
    h = _h(w.owner)
    assert client.post(f"/api/v1/knowledge/{eid}/rollback", json={"event_id": "nope"}, headers=h).status_code == 404
    created = client.get(f"/api/v1/knowledge/{eid}/history", headers=h).json()[0]
    assert client.post(f"/api/v1/knowledge/{eid}/rollback", json={"event_id": created["id"]}, headers=h).status_code == 404     # only edits can be undone
    assert client.post(f"/api/v1/knowledge/{eid}/rollback", json={"event_id": created["id"]}, headers=_h(w.ro)).status_code == 403
    assert client.get(f"/api/v1/knowledge/{eid}/history", headers=_h(w.ro)).status_code == 403
    other = _workspace(db)
    assert client.get(f"/api/v1/knowledge/{eid}/history", headers=_h(other.owner)).json() == []
    assert client.post(f"/api/v1/knowledge/{eid}/rollback", json={"event_id": created["id"]}, headers=_h(other.owner)).status_code == 404

    long_text = "x" * 4500
    big = make(client, w, content=long_text)
    client.patch(f"/api/v1/knowledge/{big}", json={"content": "short"}, headers=h)
    ev = client.get(f"/api/v1/knowledge/{big}/history", headers=h).json()[0]
    assert client.post(f"/api/v1/knowledge/{big}/rollback", json={"event_id": ev["id"]}, headers=h).status_code == 409
    assert db.query(KnowledgeEntry).filter_by(id=big).one().content == "short"                 # nothing half-restored
